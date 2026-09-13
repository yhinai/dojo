"""Seed a fixture experiment so the dashboard and demo can be built without credentials.

Every attempt is written with mode="test". `sync-weave` refuses fixture experiments and
`assemble_demo.py` rejects them, so this data can never be presented as a measured result.
The control room shows its "Fixture data" banner for the same reason.

Two outcomes are available because both demo scripts must be rehearsed:

    --outcome admit   at least one lesson clears the gate and the pool grows
    --outcome null    every candidate exhausts its evidence and the pool stays empty

Usage:
    HERD_STATE_DIR=experiments-fixture uv run python scripts/seed_fixture_experiment.py --outcome admit
    HERD_STATE_DIR=experiments-fixture uv run herd serve --demo
    HERD_STATE_DIR=experiments-fixture uv run herd control-room
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
from pathlib import Path

from herd.config import configuration
from herd.engine import Engine
from herd.schemas import AttemptRecord, BehaviorResult, CheckResult, LessonDraft, Partition, digest
from herd.store import Store
from herd.task_registry import CONTRACTS, TaskRegistry

# Per-arm success probabilities for the final comparison. Ordered so the demo has a
# curated-docs baseline that is genuinely competitive, which is the honest shape.
ARM_SUCCESS = {"no_pool": 0.35, "curated_docs": 0.55, "raw_memory": 0.50, "admitted_pool": 0.70}
NULL_ARM_SUCCESS = {"no_pool": 0.52, "curated_docs": 0.55, "raw_memory": 0.50, "admitted_pool": 0.53}


class FixtureLearner:
    """Deterministic stand-in for a model worker. Never calls a provider.

    Deliberately exposes no `gateway` attribute: Engine.develop then records the
    semantic curator as `fixture_static_only` instead of demanding a live one.
    """

    def __init__(self, outcome: str):
        self.outcome = outcome

    @staticmethod
    def _rng(*parts) -> random.Random:
        return random.Random(digest(list(parts)))

    def _succeeds(self, task, identity, arm, memory) -> bool:
        rng = self._rng(task.task_id, identity, arm, self.outcome)
        if task.partition == Partition.REGRESSION:
            return True  # controls must stay green or every candidate is vetoed
        if task.partition == Partition.FINAL:
            table = ARM_SUCCESS if self.outcome == "admit" else NULL_ARM_SUCCESS
            return rng.random() < table.get(arm, 0.5)
        if task.partition == Partition.ADMISSION:
            # A planted false lesson must lose, or the negative control proves nothing and
            # the "rejected false lesson" demo beat cannot be rehearsed. controls.false_drafts
            # ids every diagnostic candidate `poison-*`, and retrieval puts that id in memory.
            if "poison-" in (memory or ""):
                return arm == "control"
            if self.outcome == "null":
                # Both arms behave identically: every pair is a tie, evidence never accrues.
                return rng.random() < 0.5
            return arm == "treatment" or rng.random() < 0.25
        if task.partition == Partition.DEVELOPMENT:
            return True  # succeeds on the repair, which is what licenses a lesson
        return rng.random() < 0.6

    async def attempt(self, task, run_id, identity, round_id, pool_hash, memory="", arm="admitted_pool"):
        success = self._succeeds(task, identity, arm, memory)
        repaired = task.partition == Partition.DEVELOPMENT
        contract = CONTRACTS.get(task.public_fixture.get("operation"), "slider")
        failing = {
            "duplicate_repair": "structure_repair_cells",
            "local_scope": "structure_separate_previews",
            "forward_dependency": "structure_forward_dependency",
        }.get(contract, "initial_result")
        initial = BehaviorResult(
            task_id=task.task_id,
            success=False,
            mode="test",
            checks=[
                CheckResult(
                    name=failing,
                    passed=False,
                    detail=f"MultipleDefinitionError: 'total' defined in 2 cells ({contract})",
                ),
                CheckResult(name="integrity", passed=True),
            ],
        )
        return AttemptRecord(
            run_id=run_id,
            task_id=task.task_id,
            learner_id=identity,
            round_id=round_id,
            pool_hash=pool_hash,
            arm=arm,
            status="completed",
            mode="test",
            cost_usd=0.0,
            tool_calls=3 if repaired else 2,
            submissions=2 if repaired else 1,
            input_tokens=2400,
            output_tokens=900,
            initial_source="# fixture: first submission\n" + ("x = 1\nx = 2\n" if repaired else ""),
            source="# fixture: repaired submission\n_tmp = 1\ntotal = _tmp\n",
            first_submission_success=False if repaired else success,
            initial_result=initial if repaired else None,
            result=BehaviorResult(
                task_id=task.task_id,
                success=success,
                mode="test",
                checks=[
                    CheckResult(name="startup", passed=True),
                    CheckResult(name="semantic_probe", passed=success),
                    CheckResult(name="integrity", passed=True),
                ],
            ),
        )

    async def distill(self, attempt: AttemptRecord, task):
        if not (attempt.result and attempt.result.success and attempt.submissions > 1):
            return None
        contract = CONTRACTS.get(task.public_fixture.get("operation"), "slider")
        # Distinct text per contract, otherwise the curator dedupes every sibling and
        # later rounds produce nothing, which makes the pool-growth beat unrehearsable.
        lessons = {
            "duplicate_repair": (
                ("When two cells each need a scratch value, give each its own global name or "
                 "prefix it with an underscore to keep it cell-local."),
                "A value a downstream cell reads stays a shared definition.",
                "_running = sum(values)\nsubtotal = _running",
            ),
            "local_scope": (
                ("Name a per-cell temporary with a leading underscore so sibling cells can reuse "
                 "the same identifier without colliding in the dependency graph."),
                "Do not underscore a value another cell must import.",
                "_rows = [r for r in data if r]\npositive = _rows",
            ),
            "forward_dependency": (
                ("Cell order in the file does not set execution order; a cell may read a global "
                 "defined further down, so place cells for readability and let dependencies resolve."),
                "It does not permit two cells to define the same global.",
                "# transform may appear above the cell defining `records`",
            ),
            "form": (
                ("Wrap a control in .form() when edits must not take effect until submission, and "
                 "read the committed value downstream rather than the live widget value."),
                "A control that should update immediately must not be wrapped.",
                "control = mo.ui.slider(1, 10).form(submit_button_label='Apply')",
            ),
            "state": (
                ("Bind the widget's on_change to the state setter and read the getter downstream, "
                 "so direct state writes and widget events both drive recomputation."),
                "A value only ever set by one widget needs no state.",
                "get_v, set_v = mo.state(1)\nctl = mo.ui.slider(on_change=set_v)",
            ),
            "stop": (
                ("Call mo.stop before computing, not after, so the guarded value is never defined "
                 "when the condition holds and downstream cells stop cleanly."),
                "Do not use mo.stop for a value that must always exist.",
                "mo.stop(not enabled.value, mo.md('Paused'))\nresult = compute(rows)",
            ),
            "table": (
                ("Compute over the table's selection rather than the full dataset, and treat an "
                 "empty selection as an empty input instead of falling back to every row."),
                "Does not apply when the task asks for an aggregate over all rows.",
                "rows = selection_table.value\ntotal = sum(r['amount'] for r in rows)",
            ),
        }
        text, exclusion, example = lessons.get(contract, lessons["duplicate_repair"])
        return LessonDraft(
            lesson_id="lesson-" + digest(attempt.run_id)[:20],
            tool="marimo",
            runtime_lock_hash=task.runtime_lock_hash,
            scope_tags=task.public_skill_tags,
            trigger=f"When authoring a {contract.replace('_', ' ')} notebook",
            instruction=text,
            does_not_apply=exclusion,
            generic_example=example,
            origin_learner_id=attempt.learner_id,
            origin_round=attempt.round_id,
            origin_task_ids=[task.task_id],
            repair_run_ids=[attempt.run_id],
        )


async def seed(state_dir: Path, outcome: str, experiment_id: str) -> str:
    config = configuration()
    store = Store(state_dir / "herd.sqlite3")
    registry = TaskRegistry(config["runtime_hash"], config["docs_hash"])
    engine = Engine(store, registry, FixtureLearner(outcome), state_dir, f"fixture-{outcome}", concurrency=8)
    if store.get(experiment_id, "experiment", experiment_id) is None:
        engine.create(experiment_id)
    await engine.run(experiment_id)
    return experiment_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcome", choices=("admit", "null"), default="admit")
    parser.add_argument("--experiment-id", default=None, help="default: fixture-<outcome>")
    parser.add_argument("--state-dir", default=os.getenv("HERD_STATE_DIR", "experiments-fixture"))
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    if state_dir.name == "experiments":
        parser.error("refusing to seed fixture data into the live 'experiments' directory")
    state_dir.mkdir(parents=True, exist_ok=True)
    experiment_id = args.experiment_id or f"fixture-{args.outcome}"

    eid = asyncio.run(seed(state_dir, args.outcome, experiment_id))

    store = Store(state_dir / "herd.sqlite3")
    experiment = store.get(eid, "experiment", eid) or {}
    counts = {k: len(store.list(eid, k)) for k in ("attempt", "lesson", "gate", "pair", "pool", "report")}
    admitted = [x for x in store.list(eid, "lesson") if x.get("status") == "admitted"]
    print(f"seeded {eid}  status={experiment.get('status')}  outcome={args.outcome}")
    print(f"  {counts}")
    print(f"  admitted lessons: {len(admitted)}")
    print(f"\n  HERD_STATE_DIR={state_dir} uv run herd serve --demo")
    print(f"  HERD_STATE_DIR={state_dir} uv run herd control-room")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import asyncio

import pytest

from herd.engine import Engine, safe_gather
from herd.schemas import AttemptRecord, BehaviorResult, CheckResult, Partition, PoolSnapshot, TaskManifest
from herd.store import Store


@pytest.mark.asyncio
async def test_safe_gather_drains_cancelled_workers():
    state = []

    async def slow():
        try:
            await asyncio.sleep(10)
            state.append("unexpected write")
        finally:
            state.append("drained")

    async def fail():
        await asyncio.sleep(0.01)
        raise RuntimeError("cap")

    with pytest.raises(RuntimeError):
        await safe_gather(slow(), fail())
    assert state == ["drained"]


class Registry:
    def generate(self, partition, seed, track=None):
        return TaskManifest(
            task_id=f"{partition}-{seed}",
            template_id="f",
            family_id="f",
            track=track or 0,
            partition=partition,
            public_request="Task",
            runtime_lock_hash="r",
            docs_snapshot_hash="d",
        )


@pytest.mark.asyncio
async def test_composition_controls_compare_incumbent_to_proposed(tmp_path):
    engine = Engine(Store(tmp_path / "db"), Registry(), None, tmp_path, "model")
    incumbent = PoolSnapshot(pool_hash="old", experiment_id="e", round_id=1)
    proposed = PoolSnapshot(pool_hash="new", experiment_id="e", round_id=1)
    calls = []

    async def attempt(eid, task, identity, round_id, pool, arm, candidate=None):
        calls.append((pool.pool_hash, arm))
        success = pool.pool_hash == "old"
        return AttemptRecord(
            run_id=arm,
            task_id=task.task_id,
            learner_id=identity,
            round_id=round_id,
            pool_hash=pool.pool_hash,
            status="completed",
            result=BehaviorResult(
                task_id=task.task_id, success=success, checks=[CheckResult(name="integrity", passed=success)]
            ),
        )

    engine.attempt = attempt
    assert not await engine.controls("e", 1, incumbent, treatment_pool=proposed)
    assert calls == [("old", "control"), ("new", "treatment")]


@pytest.mark.asyncio
async def test_prepared_round_commit_recovers_without_relearning(tmp_path):
    store = Store(tmp_path / "db")
    engine = Engine(store, Registry(), None, tmp_path, "model")
    engine.create("e")
    old = engine.pool("e")
    proposed = PoolSnapshot(pool_hash="new", experiment_id="e", round_id=1, parent_hash=old.pool_hash)
    store.put("e", "pool", "new", proposed)
    store.put("e", "round", "1", {"complete": False, "start_pool": old.pool_hash, "prepared_pool": "new"})
    # Simulate crash after CAS head, before marking round complete.
    store.put("e", "head", "current", {"pool_hash": "new"})
    for n in (2, 3):
        store.put("e", "round", str(n), {"complete": True})

    async def final(eid):
        pass

    engine.final = final
    engine.run_false_controls = final
    result = await engine.run("e")
    assert result["status"] == "complete"
    assert store.get("e", "round", "1")["complete"]


@pytest.mark.asyncio
async def test_full_protocol_fixture_run_and_resume(tmp_path):
    """Deterministic orchestration proof, not an empirical learning experiment."""
    from herd.schemas import LessonDraft

    class FullRegistry(Registry):
        def generate(self, partition, seed, track=None):
            result = super().generate(partition, seed, track)
            return result.model_copy(
                update={"family_id": f"family-{seed % 12}", "public_skill_tags": ["cells"]}
            )

    class FixtureLearner:
        def __init__(self):
            self.calls = []

        async def attempt(self, task, run_id, identity, round_id, pool_hash, memory, arm):
            self.calls.append((task.partition, identity, round_id, pool_hash, arm))
            success = task.partition in (Partition.DEVELOPMENT, Partition.REGRESSION) or arm == "treatment"
            if task.partition == Partition.FINAL:
                success = bool(memory and memory != "[]")
            return AttemptRecord(
                run_id=run_id,
                task_id=task.task_id,
                learner_id=identity,
                round_id=round_id,
                pool_hash=pool_hash,
                arm=arm,
                status="completed",
                mode="test",
                cost_usd=0,
                initial_source="fixture-failure",
                source="fixture-repair",
                first_submission_success=False,
                submissions=2,
                result=BehaviorResult(
                    task_id=task.task_id,
                    success=success,
                    mode="test",
                    checks=[
                        CheckResult(name="semantic_probe", passed=success),
                        CheckResult(name="integrity", passed=True),
                    ],
                ),
            )

        async def distill(self, attempt, task):
            return LessonDraft(
                lesson_id=f"lesson-{attempt.learner_id}-{attempt.round_id}",
                runtime_lock_hash="r",
                scope_tags=["cells"],
                trigger="When authoring a cell",
                instruction=f"Use a uniquely defined cell variable: {attempt.learner_id} round {attempt.round_id}.",
                does_not_apply="Not for independent notebook files.",
                origin_learner_id=attempt.learner_id,
                origin_round=attempt.round_id,
                origin_task_ids=[task.task_id],
                repair_run_ids=[attempt.run_id],
            )

    store = Store(tmp_path / "full.db")
    learner = FixtureLearner()
    engine = Engine(store, FullRegistry(), learner, tmp_path, "fixture-model")
    engine.create("fixture")
    result = await engine.run("fixture")
    assert result["status"] == "complete"
    development = [x for x in learner.calls if x[0] == Partition.DEVELOPMENT]
    assert len(development) == 45
    assert len({x[1] for x in development}) == 5
    for round_id in (1, 2, 3):
        round_calls = [x for x in development if x[2] == round_id]
        assert len(round_calls) == 15
        assert len({x[3] for x in round_calls}) == 1
    gates = store.list("fixture", "gate")
    assert len(gates) == 15
    assert {g["slot_id"] for g in gates} == set(range(15))
    assert all(g["decision"] == "admitted" for g in gates)
    finals = [x for x in learner.calls if x[0] == Partition.FINAL]
    assert len(finals) == 720
    assert {
        arm: sum(x[4] == arm for x in finals)
        for arm in ("no_pool", "curated_docs", "raw_memory", "admitted_pool")
    } == {"no_pool": 180, "curated_docs": 180, "raw_memory": 180, "admitted_pool": 180}
    assert len(store.list("fixture", "raw_slot")) == 15
    count = len(learner.calls)
    await engine.run("fixture")
    assert len(learner.calls) == count
    assert store.verify_events("fixture")


@pytest.mark.asyncio
async def test_false_lesson_veto_uses_real_gate_pipeline_without_primary_slots(tmp_path):
    """Fixture worker exercises control wiring; does not assert empirical poisoning resistance."""

    class Worker:
        async def attempt(self, task, run_id, identity, round_id, pool_hash, memory, arm):
            passed = arm != "treatment"
            return AttemptRecord(
                run_id=run_id,
                task_id=task.task_id,
                learner_id=identity,
                round_id=round_id,
                pool_hash=pool_hash,
                arm=arm,
                status="completed",
                mode="test",
                result=BehaviorResult(
                    task_id=task.task_id,
                    success=passed,
                    mode="test",
                    checks=[CheckResult(name="semantic_probe", passed=passed)],
                ),
            )

    store = Store(tmp_path / "control.db")
    engine = Engine(store, Registry(), Worker(), tmp_path, "fixture")
    engine.create("e")
    head = engine.pool("e").pool_hash
    results = await engine.run_false_controls("e")
    assert len(results) == 3
    assert all(r["decision"] == "rejected" and r["safeguard_passed"] for r in results)
    assert len(store.list("e", "control_gate")) == 3
    assert not store.list("e", "gate_slot") and not store.list("e", "lesson")
    assert engine.pool("e").pool_hash == head
    before = len(store.list("e", "attempt"))
    await engine.run_false_controls("e")
    assert len(store.list("e", "attempt")) == before


@pytest.mark.asyncio
async def test_pause_drains_active_workers_and_stops_waiting_units(tmp_path):
    store = Store(tmp_path / "pause.db")
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    class Worker:
        async def attempt(self, task, run_id, identity, round_id, pool_hash, memory, arm):
            calls.append(run_id)
            started.set()
            await release.wait()
            return AttemptRecord(
                run_id=run_id,
                task_id=task.task_id,
                learner_id=identity,
                round_id=round_id,
                pool_hash=pool_hash,
                arm=arm,
                status="completed",
                mode="test",
            )

    engine = Engine(store, Registry(), Worker(), tmp_path, "fixture", concurrency=1)
    engine.create("e")
    pool = engine.pool("e")
    jobs = asyncio.create_task(
        safe_gather(
            *[
                engine.attempt("e", engine.task("e", Partition.DEVELOPMENT, i), str(i), 1, pool)
                for i in range(3)
            ]
        )
    )
    await started.wait()
    store.request_control("e", "pause")
    release.set()
    from herd.engine import RunInterrupted

    with pytest.raises(RunInterrupted):
        await jobs
    assert len(calls) == 1
    assert store.list("e", "attempt")[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_regression_controls_require_explicit_integrity_in_both_arms(tmp_path):
    store = Store(tmp_path / "integrity.db")
    engine = Engine(store, Registry(), None, tmp_path, "fixture")
    pool = PoolSnapshot(pool_hash="p", experiment_id="e", round_id=1)

    async def attempt(eid, task, identity, round_id, pool, arm, candidate=None):
        return AttemptRecord(
            run_id=arm,
            task_id=task.task_id,
            learner_id=identity,
            round_id=round_id,
            pool_hash=pool.pool_hash,
            status="completed",
            mode="test",
            result=BehaviorResult(
                task_id=task.task_id,
                success=False,
                mode="test",
                checks=[CheckResult(name="semantic_probe", passed=False)],
            ),
        )

    engine.attempt = attempt
    assert not await engine.controls("e", 1, pool)


@pytest.mark.asyncio
async def test_auxiliary_model_calls_share_episode_resource_ceiling(tmp_path):
    from herd.schemas import LessonDraft

    store = Store(tmp_path / "aux.db")
    active = 0
    peak = 0
    kinds = []

    async def instrument(kind):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        kinds.append(kind)
        await asyncio.sleep(0.003)
        active -= 1

    class Gateway:
        async def complete(self, *args, **kwargs):
            from herd.gateway import Completion

            await instrument("semantic")
            return Completion('{"decision":"clear","confidence":0.95,"findings":[]}', 1, 1, 0)

    class Worker:
        gateway = Gateway()

        async def attempt(self, task, run_id, identity, round_id, pool_hash, memory, arm):
            await instrument("attempt")
            return AttemptRecord(
                run_id=run_id,
                task_id=task.task_id,
                learner_id=identity,
                round_id=round_id,
                pool_hash=pool_hash,
                arm=arm,
                status="completed",
                mode="test",
                submissions=2,
                first_submission_success=False,
                result=BehaviorResult(
                    task_id=task.task_id,
                    success=True,
                    mode="test",
                    checks=[
                        CheckResult(name="semantic_probe", passed=True),
                        CheckResult(name="integrity", passed=True),
                    ],
                ),
            )

        async def distill(self, attempt, task):
            await instrument("distill")
            return LessonDraft(
                lesson_id="lesson-" + attempt.learner_id,
                runtime_lock_hash=task.runtime_lock_hash,
                scope_tags=["cells"],
                trigger="When authoring cells",
                instruction="Define a public variable only once.",
                does_not_apply="Independent files have separate namespaces.",
                origin_learner_id=attempt.learner_id,
                origin_round=attempt.round_id,
                origin_task_ids=[task.task_id],
                repair_run_ids=[attempt.run_id],
            )

    engine = Engine(store, Registry(), Worker(), tmp_path, "fixture", concurrency=1)
    engine.create("e")
    await safe_gather(*(engine.develop("e", 1, engine.pool("e"), i) for i in range(5)))
    assert peak == 1
    assert {kind: kinds.count(kind) for kind in set(kinds)} == {"attempt": 15, "distill": 5, "semantic": 5}


def test_curated_baseline_is_distinct_and_frozen(tmp_path):
    from herd.config import ROOT

    engine = Engine(Store(tmp_path / "baseline.db"), Registry(), None, tmp_path, "fixture")
    exp = engine.create("e")
    assert exp["config"]["curated_docs"] == (ROOT / "docs/snapshots/curated-marimo.md").read_text()
    assert exp["config"]["curated_docs"] != (ROOT / "docs/snapshots/marimo.md").read_text()
    from herd.schemas import digest

    assert exp["config"]["curated_docs_hash"] == digest(exp["config"]["curated_docs"])

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


class RuntimeRetryWorker:
    def __init__(self, failures=1, provider=False):
        self.calls = []
        self.failures = failures
        self.provider = provider

    async def attempt(self, task, run_id, identity, round_id, pool_hash, memory, arm):
        self.calls.append((run_id, identity, arm))
        failed = self.failures > 0 and arm != "treatment"
        if failed:
            self.failures -= 1
        return AttemptRecord(
            run_id=run_id,
            task_id=task.task_id,
            learner_id=identity,
            round_id=round_id,
            pool_hash=pool_hash,
            arm=arm,
            mode="test",
            status="infrastructure_error" if failed else "completed",
            infrastructure_kind=("provider" if self.provider else "runtime") if failed else None,
            result=BehaviorResult(
                task_id=task.task_id,
                success=not failed,
                mode="test",
                infrastructure_error="transient runtime" if failed else None,
                checks=[CheckResult(name="integrity", passed=not failed)],
            ),
        )


@pytest.mark.asyncio
async def test_pair_retry_reexecutes_both_arms_once_and_resume_reuses_evidence(tmp_path):
    store = Store(tmp_path / "retry.db")
    worker = RuntimeRetryWorker()
    engine = Engine(store, Registry(), worker, tmp_path, "fixture")
    engine.create("e")
    task = engine.task("e", Partition.ADMISSION, 3)
    pool = engine.pool("e")
    pair = await engine.evaluate_pair("e", task, "pair", 1, pool, None)
    assert all(x.result.success for x in pair)
    assert len(worker.calls) == 4
    assert len({x[0] for x in worker.calls}) == 4
    assert {x[1] for x in worker.calls} == {"pair", "pair:pair-runtime-retry"}
    assert len(store.list("e", "pair_retry")) == 1
    repeated = await engine.evaluate_pair("e", task, "pair", 1, pool, None)
    assert [x.run_id for x in repeated] == [x.run_id for x in pair]
    assert len(worker.calls) == 4


@pytest.mark.asyncio
async def test_runtime_attempt_retry_preserves_first_record(tmp_path):
    store = Store(tmp_path / "retry.db")
    worker = RuntimeRetryWorker()
    engine = Engine(store, Registry(), worker, tmp_path, "fixture")
    engine.create("e")
    task = engine.task("e", Partition.DEVELOPMENT, 3)
    resolved = await engine.attempt("e", task, "learner", 1, engine.pool("e"))
    assert resolved.result.success and resolved.retry_of
    assert store.get("e", "attempt", resolved.retry_of)["status"] == "infrastructure_error"
    await engine.attempt("e", task, "learner", 1, engine.pool("e"))
    assert len(worker.calls) == 2


@pytest.mark.asyncio
async def test_provider_error_never_gets_fresh_billed_retry(tmp_path):
    from herd.gateway import GatewayError

    worker = RuntimeRetryWorker(provider=True)
    engine = Engine(Store(tmp_path / "retry.db"), Registry(), worker, tmp_path, "fixture")
    engine.create("e")
    with pytest.raises(GatewayError, match="no automatic billed retry"):
        await engine.attempt("e", engine.task("e", Partition.DEVELOPMENT, 0), "learner", 1, engine.pool("e"))
    assert len(worker.calls) == 1
    assert not engine.store.list("e", "runtime_retry")


@pytest.mark.asyncio
async def test_regression_infrastructure_does_not_reject_lesson(tmp_path):
    from herd.engine import PairedInfrastructureError

    worker = RuntimeRetryWorker(failures=2)
    engine = Engine(Store(tmp_path / "retry.db"), Registry(), worker, tmp_path, "fixture")
    engine.create("e")
    with pytest.raises(PairedInfrastructureError):
        await engine.controls("e", 1, engine.pool("e"))
    assert len(worker.calls) == 4
    assert len(engine.store.list("e", "pair_retry")) == 2
    assert not engine.store.list("e", "lesson")
    # An explicit subsequent invocation may recover the control, without rewriting failed attempts.
    assert await engine.controls("e", 1, engine.pool("e"))
    assert len(engine.store.list("e", "attempt")) == 14


@pytest.mark.asyncio
async def test_invalid_pair_is_consumed_once_and_resume_draws_new_task(tmp_path):
    from herd.engine import PairedInfrastructureError
    from herd.schemas import LessonRevision

    worker = RuntimeRetryWorker(failures=2)
    engine = Engine(Store(tmp_path / "gate-retry.db"), Registry(), worker, tmp_path, "fixture")
    engine.create("e")

    async def passing_controls(*args, **kwargs):
        return True

    engine.controls = passing_controls
    candidate = LessonRevision(
        lesson_id="lesson",
        runtime_lock_hash="r",
        scope_tags=["cells"],
        trigger="When defining cells",
        instruction="Define each public name once.",
        does_not_apply="Not across independent files.",
        origin_learner_id="learner",
        origin_round=1,
        origin_task_ids=["dev"],
        repair_run_ids=["repair"],
    )
    with pytest.raises(PairedInfrastructureError):
        await engine.gate("e", 1, engine.pool("e"), candidate, 0)
    state = engine.store.list("e", "gate")[0]
    assert state["invalid"] == 1 and len(state["pair_ids"]) == 1
    assert state["log_e"] == 0 and state["decision"] == "evaluating"
    invalid_pair = engine.store.list("e", "pair")[0]
    assert not invalid_pair["valid"]
    first_ids = {x[0] for x in worker.calls}
    await engine.gate("e", 1, engine.pool("e"), candidate, 0)
    state = engine.store.list("e", "gate")[0]
    assert state["invalid"] == 1
    assert len(state["task_ids"]) == len(set(state["task_ids"]))
    assert len([x for x in worker.calls if x[0] in first_ids]) == 4


@pytest.mark.asyncio
async def test_sibling_duplicates_and_conflicts_quarantine_at_commit(tmp_path):
    from herd.schemas import LessonRevision, LessonStatus

    engine = Engine(Store(tmp_path / "composition.db"), Registry(), None, tmp_path, "fixture")
    engine.create("e")

    async def develop(eid, round_id, pool, index):
        if round_id != 1 or index > 2:
            return None
        return LessonRevision(
            lesson_id=f"lesson-{index}",
            runtime_lock_hash="r",
            scope_tags=["cells"],
            trigger="When defining cells",
            instruction="Define each public name once." if index < 2 else "Other advice.",
            does_not_apply="Not across independent files.",
            origin_learner_id=f"learner-{index}",
            origin_round=1,
            origin_task_ids=[f"dev-{index}"],
            repair_run_ids=[f"repair-{index}"],
            conflicts_with=["lesson-0"] if index == 2 else [],
        )

    # Individually admitted siblings must still pass deterministic composition checks.
    async def gate(eid, round_id, pool, candidate, slot):
        candidate.status = LessonStatus.ADMITTED
        candidate.trial_id = f"trial-{slot}"
        return candidate

    async def controls(*args, **kwargs):
        return True

    async def nothing(*args):
        return None

    engine.develop, engine.gate, engine.controls = develop, gate, controls
    engine.final = engine.run_false_controls = nothing
    await engine.run("e")
    assert [x.lesson_id for x in engine.pool("e").lessons] == ["lesson-0"]
    assert engine.store.get("e", "lesson", "lesson-2")["status"] == "quarantined"
    duplicate = engine.store.get("e", "lesson", "lesson-1")
    assert duplicate["status"] == "quarantined" and "duplicate" in duplicate["decision_reason"]
    assert any(x["event_type"] == "lesson.composition_quarantined" for x in engine.store.events("e"))


@pytest.mark.asyncio
async def test_exhausted_runtime_retry_requires_new_execution_epoch(tmp_path):
    from herd.gateway import GatewayError

    worker = RuntimeRetryWorker(failures=2)
    engine = Engine(Store(tmp_path / "retry.db"), Registry(), worker, tmp_path, "fixture")
    engine.create("e")
    task = engine.task("e", Partition.DEVELOPMENT, 0)
    pool = engine.pool("e")
    for _ in range(2):
        with pytest.raises(GatewayError, match="failed twice"):
            await engine.attempt("e", task, "learner", 1, pool)
    assert len(worker.calls) == 2
    experiment = engine.store.get("e", "experiment", "e")
    experiment["execution_epoch"] = 1
    engine.store.put("e", "experiment", "e", experiment)
    recovered = await engine.attempt("e", task, "learner", 1, pool)
    assert recovered.result.success
    assert len(worker.calls) == 3 and len({x[0] for x in worker.calls}) == 3
    assert len(engine.store.list("e", "attempt")) == 3


@pytest.mark.asyncio
async def test_cached_pair_does_not_emit_new_live_evaluation(tmp_path, monkeypatch):
    calls = []

    async def log(name, attempts, metadata):
        calls.append([a.run_id for a in attempts])
        return {"status": "logged", "mode": "actual_worker_execution"}

    monkeypatch.setattr("herd.integrations.weave.log_execution_pair", log)
    engine = Engine(
        Store(tmp_path / "live.db"), Registry(), RuntimeRetryWorker(failures=0), tmp_path, "fixture"
    )
    engine.create("e")
    task = engine.task("e", Partition.ADMISSION, 3)
    for _ in range(2):
        await engine.evaluate_pair("e", task, "pair", 1, engine.pool("e"), None)
    assert len(calls) == 1
    assert len(engine.store.list("e", "live_evaluation")) == 1


def scoped_candidate(registry, seed=5):
    from herd.schemas import LessonDraft

    origin = registry.generate(Partition.DEVELOPMENT, seed)
    draft = LessonDraft(
        lesson_id="lesson-scoped",
        runtime_lock_hash=origin.runtime_lock_hash,
        scope_tags=origin.public_skill_tags,
        trigger="When authoring this contract",
        instruction="Give each cell-local scratch value its own underscored name.",
        does_not_apply="Not for a value another cell must read.",
        generic_example="_running = sum(values)",
        origin_learner_id="learner-0",
        origin_round=1,
        origin_task_ids=[origin.task_id],
        repair_run_ids=["run-0"],
    )
    return origin, draft


def gate_state(candidate, slot=0):
    from herd.schemas import GateState, TrialBinding

    binding = TrialBinding(
        candidate_hash=candidate.content_hash,
        incumbent_pool_hash="pool",
        retriever_hash="retriever",
        model_config_hash="model",
        runtime_lock_hash="runtime",
        docs_snapshot_hash="docs",
        sampler_hash="sampler",
    )
    return GateState(trial_id="trial", slot_id=slot, binding=binding)


def drain(engine, state, candidate, slot=0, diagnostic=False):
    tasks = []
    for index in range(state.max_pairs):
        task = engine.admission_task("e", state, candidate, slot, index, diagnostic)
        state.task_ids.append(task.task_id)
        tasks.append(task)
    return tasks


def test_admission_sampler_draws_the_whole_budget_from_the_candidate_scope(tmp_path):
    """An unscoped uniform draw made admission arithmetically unreachable.

    Twelve families share the admission partition, so a contract-scoped lesson saw
    about five on-scope pairs in a 64-pair budget while the e-process needs eight
    consecutive wins to reach 1/alpha. No true lesson could ever be admitted.
    """
    import math

    from herd.task_registry import FAMILIES, TaskRegistry

    registry = TaskRegistry("runtime", "docs")
    engine = Engine(Store(tmp_path / "db"), registry, None, tmp_path, "model")
    reference = gate_state(scoped_candidate(registry)[1])
    needed = math.ceil(math.log(1 / reference.alpha) / math.log1p(reference.bet))
    budget = reference.max_pairs
    unscoped = [registry.generate(Partition.ADMISSION, n) for n in range(budget)]
    starved = []

    for seed in range(len(FAMILIES)):
        origin, candidate = scoped_candidate(registry, seed)
        scope = set(candidate.scope_tags)
        tasks = drain(engine, gate_state(candidate), candidate)

        assert all(task.partition == Partition.ADMISSION for task in tasks)
        assert all(scope <= set(task.public_skill_tags) for task in tasks)
        assert len({task.task_id for task in tasks}) == budget
        assert origin.task_id not in {task.task_id for task in tasks}
        assert len(tasks) >= needed

        if sum(1 for task in unscoped if scope <= set(task.public_skill_tags)) < needed:
            starved.append(origin.family_id)

    assert starved  # the defect this test pins: unscoped draws cannot reach 1/alpha


def test_admission_sampler_spreads_a_multi_family_scope_and_replays_on_resume(tmp_path):
    from herd.task_registry import CONTRACTS, TaskRegistry

    registry = TaskRegistry("runtime", "docs")
    engine = Engine(Store(tmp_path / "db"), registry, None, tmp_path, "model")
    shared = next(
        n
        for n in range(24)
        if CONTRACTS[registry.generate(Partition.DEVELOPMENT, n).public_fixture["operation"]] == "table"
    )
    _, candidate = scoped_candidate(registry, shared)

    first = [task.task_id for task in drain(engine, gate_state(candidate), candidate)]
    replay = [task.task_id for task in drain(engine, gate_state(candidate), candidate)]
    assert first == replay  # a resumed trial redraws exactly the pairs it already holds

    families = {task.family_id for task in drain(engine, gate_state(candidate), candidate)}
    assert len(families) == 2  # both families carrying the scope, not just the first hit

    other = [task.task_id for task in drain(engine, gate_state(candidate, 1), candidate, slot=1)]
    control = [
        task.task_id
        for task in drain(engine, gate_state(candidate, 1), candidate, slot=1, diagnostic=True)
    ]
    assert not set(first) & set(other)  # slots never share admission evidence
    assert not set(other) & set(control)  # negative controls draw from a disjoint seed space


def test_raw_memory_arm_uses_the_same_public_envelope_as_the_admitted_pool(tmp_path):
    """Otherwise the headline measures gating plus richer formatting, not gating."""
    import json

    from herd.curator import make_pool, raw_memory, retrieve
    from herd.schemas import LessonRevision, LessonStatus
    from herd.task_registry import TaskRegistry

    registry = TaskRegistry("runtime", "docs")
    _, draft = scoped_candidate(registry)
    admitted = LessonRevision(**draft.model_dump(), status=LessonStatus.ADMITTED)
    pool = make_pool("e", 1, [admitted])

    injected, _ = retrieve(pool, draft.scope_tags, "runtime")
    assert json.loads(injected) == raw_memory([draft], draft.scope_tags)

    task = registry.generate(Partition.FINAL, 100000)
    off_scope = raw_memory([draft], ["unrelated-tag"])
    assert off_scope == []
    if set(draft.scope_tags) & set(task.public_skill_tags):
        assert raw_memory([draft], task.public_skill_tags)[0].keys() == {
            "id",
            "when",
            "instruction",
            "except",
            "example",
        }

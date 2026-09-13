import pytest

from herd.curator import make_pool, retrieve, review_draft, semantic_review
from herd.curriculum import assigned_track, freeze_round, queue_curriculum
from herd.lifecycle import apply_pending, request_change
from herd.schemas import LessonRevision, LessonStatus, Partition, TaskManifest
from herd.store import Store


def lesson(name="one"):
    return LessonRevision(
        lesson_id=name,
        runtime_lock_hash="r",
        scope_tags=["cells"],
        trigger="When authoring cells",
        instruction="Define public variables once across cells.",
        does_not_apply="Independent notebooks do not share definitions.",
        origin_learner_id="worker",
        origin_round=1,
        origin_task_ids=["origin-task"],
        repair_run_ids=["repair-id"],
        status=LessonStatus.ADMITTED,
    )


def setup(tmp_path):
    store = Store(tmp_path / "state.db")
    empty = make_pool("e", 0, [])
    pool = make_pool("e", 1, [lesson()], empty.pool_hash)
    store.put("e", "experiment", "e", {"id": "e", "phase": "development", "round_id": 1})
    for p in (empty, pool):
        store.put("e", "pool", p.pool_hash, p)
    store.put("e", "head", "current", {"pool_hash": pool.pool_hash})
    store.put("e", "lesson", "one", lesson())
    return store, empty, pool


async def pass_validation(old, new):
    return True


@pytest.mark.asyncio
async def test_midround_retraction_rebases_and_preserves_snapshot(tmp_path):
    store, _, pool = setup(tmp_path)
    action = request_change(store, "e", "retract", "Measured harmful interaction", ["one"])
    later = make_pool("e", 2, pool.lessons + [lesson("two")], pool.pool_hash)
    store.put("e", "pool", later.pool_hash, later)
    store.put("e", "head", "current", {"pool_hash": later.pool_hash})
    await apply_pending(store, "e", 3, pass_validation)
    head = store.get("e", "head", "current")["pool_hash"]
    assert [x["lesson_id"] for x in store.get("e", "pool", head)["lessons"]] == ["two"]
    assert store.get("e", "lesson", "one")["status"] == "retracted"
    assert store.get("e", "pool", pool.pool_hash)["lessons"][0]["status"] == "admitted"
    assert store.get("e", "lifecycle", action["id"])["status"] == "applied"
    await apply_pending(store, "e", 3, pass_validation)
    assert store.get("e", "head", "current")["pool_hash"] == head


@pytest.mark.asyncio
async def test_rollback_requires_ancestor_and_restores_status(tmp_path):
    store, empty, pool = setup(tmp_path)
    # Create a later pool in which the prior lesson was removed.
    removed = make_pool("e", 2, [], pool.pool_hash)
    store.put("e", "pool", removed.pool_hash, removed)
    store.put("e", "head", "current", {"pool_hash": removed.pool_hash})
    store.put("e", "lesson", "one", lesson().model_copy(update={"status": LessonStatus.RETRACTED}))
    request_change(
        store, "e", "rollback", "Restore last known good revision", target_pool_hash=pool.pool_hash
    )
    await apply_pending(store, "e", 3, pass_validation)
    assert store.get("e", "lesson", "one")["status"] == "admitted"
    assert store.get("e", "pool", removed.pool_hash)["lessons"] == []
    store.put("e", "final_freeze", "current", {"pool_hash": pool.pool_hash})
    with pytest.raises(ValueError, match="frozen"):
        request_change(store, "e", "rollback", "Too late", target_pool_hash=empty.pool_hash)


@pytest.mark.asyncio
async def test_lifecycle_regression_veto_no_head_change(tmp_path):
    store, _, pool = setup(tmp_path)
    action = request_change(store, "e", "retract", "Verify proposed pool", ["one"])

    async def fail(old, new):
        return False

    await apply_pending(store, "e", 2, fail)
    assert store.get("e", "head", "current")["pool_hash"] == pool.pool_hash
    assert store.get("e", "lifecycle", action["id"])["status"] == "rejected"


def test_aria_curriculum_changes_only_future_development(tmp_path):
    store, _, _ = setup(tmp_path)
    round1 = freeze_round(store, "e", 1)
    store.put("e", "aria_analysis", "authentic-report-hash", {"report": "Failures concentrated on forms"})
    queue_curriculum(
        store, "e", "authentic-report-hash", {"0": 1, "1": 1, "2": 1, "3": 20, "4": 1}, "Practice forms"
    )
    assert freeze_round(store, "e", 1) == round1
    round2 = freeze_round(store, "e", 2)
    assert [assigned_track(round2, i, 0) for i in range(5)] == list(range(5))
    assert sum(assigned_track(round2, i, n) == 3 for i in range(5) for n in (1, 2)) >= 6
    with pytest.raises(ValueError, match="imported ARIA"):
        queue_curriculum(store, "e", "missing", {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1}, "No report")


def test_review_leakage_and_origin_exclusion():
    draft = lesson().model_copy(update={"instruction": "Copy origin-task result directly into the output."})
    assert any(x["code"] == "task_answer_leakage" for x in review_draft(draft, []))
    pool = make_pool("e", 0, [lesson()])
    memory, ids = retrieve(pool, ["cells"], "r", excluded_origins=["worker"])
    assert memory == "[]" and ids == []


@pytest.mark.asyncio
async def test_semantic_uncertainty_is_quarantined():
    from types import SimpleNamespace

    class Gateway:
        async def complete(self, messages, **kwargs):
            assert kwargs["max_output_tokens"] == 1000
            return SimpleNamespace(
                content='{"decision":"clear","confidence":0.3,"findings":[]}',
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.001,
            )

    task = TaskManifest(
        task_id="t",
        template_id="t",
        family_id="f",
        track=0,
        partition=Partition.DEVELOPMENT,
        public_request="Build cells",
        runtime_lock_hash="r",
        docs_snapshot_hash="d",
    )
    result = await semantic_review(Gateway(), lesson(), [], task)
    assert result["decision"] == "quarantine" and result["advisory"]


def test_curriculum_largest_remainder_allocation_is_proportional_and_spread():
    from collections import Counter

    from herd.curriculum import extra_schedule

    weights = {"0": 20, "1": 20, "2": 20, "3": 20, "4": 1}
    schedule = extra_schedule(weights)
    assert len(schedule) == 10
    assert Counter(schedule) == {0: 3, 1: 3, 2: 2, 3: 2}
    assert schedule[:4] == [0, 1, 2, 3]
    for i in range(5):
        assert abs(Counter(schedule)[i] - 10 * weights[str(i)] / sum(weights.values())) < 1
    assert schedule == extra_schedule(weights)


@pytest.mark.asyncio
async def test_semantic_oversized_context_quarantines_without_provider_request():
    class Gateway:
        async def complete(self, *args, **kwargs):
            raise AssertionError("Oversized review must never call the model")

    task = TaskManifest(
        task_id="t",
        template_id="t",
        family_id="f",
        track=0,
        partition=Partition.DEVELOPMENT,
        public_request="Build a notebook",
        runtime_lock_hash="r",
        docs_snapshot_hash="d",
    )
    pool = [lesson(str(i)).model_copy(update={"instruction": "Context content " * 350}) for i in range(15)]
    result = await semantic_review(Gateway(), lesson(), pool, task)
    assert result["decision"] == "quarantine"
    assert result["findings"][0]["code"] == "review_context_budget"
    assert result["cost_usd"] == 0

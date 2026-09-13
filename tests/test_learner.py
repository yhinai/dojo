import json

import pytest

from herd.gateway import Completion
from herd.learner import Learner
from herd.schemas import BehaviorResult, CheckResult, Partition, TaskManifest


class FixtureGateway:
    mode = "test"

    def __init__(self):
        self.prompts = []

    async def complete(self, messages, max_output_tokens, request_id, max_input_tokens=None):
        self.prompts.append(json.dumps(messages))
        if request_id.endswith(":distill"):
            result = {
                "trigger": "When sharing cell variables",
                "instruction": "Define each variable in exactly one cell.",
                "does_not_apply": "Does not apply to local private names.",
            }
        else:
            result = {"action": "submit", "source": "good" if request_id.endswith(":1") else "bad"}
        return Completion(json.dumps(result), 10, 10, 0.001)


class FixtureEvaluator:
    mode = "test"

    async def evaluate(self, task, source, workspace, browser=False):
        assert browser is True
        return BehaviorResult(
            task_id=task.task_id,
            success=source == "good",
            mode="test",
            checks=[
                CheckResult(
                    name="semantic_probe",
                    passed=source == "good",
                    detail="hidden input=9234",
                    evidence={"expected": 99999},
                )
            ],
        )


def task():
    return TaskManifest(
        task_id="task",
        template_id="private-family",
        family_id="private-family",
        track=0,
        partition=Partition.DEVELOPMENT,
        public_request="Make a notebook.",
        public_skill_tags=["cells"],
        runtime_lock_hash="runtime",
        docs_snapshot_hash="docs",
    )


@pytest.mark.asyncio
async def test_verified_repair_distills_without_hidden_probe_leak(tmp_path):
    gateway = FixtureGateway()
    learner = Learner(gateway, FixtureEvaluator(), tmp_path)
    attempt = await learner.attempt(task(), "r1", "a1", 1, "empty")
    assert attempt.result.success and not attempt.first_submission_success
    assert attempt.submissions == 2 and attempt.mode == "test"
    lesson = await learner.distill(attempt, task())
    assert lesson.repair_run_ids == ["r1"]
    assert all("9234" not in p and "99999" not in p and "private-family" not in p for p in gateway.prompts)
    task_final = task().model_copy(update={"partition": Partition.FINAL})
    assert await learner.distill(attempt, task_final) is None


@pytest.mark.asyncio
async def test_live_learner_rejects_local_execution(tmp_path):
    gateway = FixtureGateway()
    gateway.mode = "measured"
    attempt = await Learner(gateway, FixtureEvaluator(), tmp_path).attempt(task(), "r", "a", 1, "p")
    assert attempt.status == "infrastructure_error"
    assert not gateway.prompts


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["Docker unavailable", "Chromium missing OS library"])
async def test_measured_runtime_not_ready_never_spends_tokens(tmp_path, reason):
    class UnavailableEvaluator:
        mode = "docker"

        async def preflight(self, browser=False):
            assert browser is True
            return {"ready": False, "reason": reason}

        async def evaluate(self, *args, **kwargs):
            raise AssertionError("Unavailable runtime must not execute")

    gateway = FixtureGateway()
    gateway.mode = "measured"
    attempt = await Learner(gateway, UnavailableEvaluator(), tmp_path).attempt(task(), "r", "a", 1, "p")
    assert attempt.status == "infrastructure_error"
    assert attempt.result.infrastructure_error == reason
    assert attempt.cost_usd == 0 and attempt.input_tokens == 0 and attempt.output_tokens == 0
    assert not gateway.prompts


@pytest.mark.asyncio
@pytest.mark.parametrize("partition", list(Partition))
async def test_browser_partition_policy_and_initial_failure_evidence(tmp_path, partition):
    from herd.learner import requires_browser

    class Evaluator(FixtureEvaluator):
        async def evaluate(self, task, source, workspace, browser=False):
            assert browser == (
                partition in (Partition.DEVELOPMENT, Partition.CALIBRATION, Partition.DEMONSTRATION)
            )
            return BehaviorResult(
                task_id=task.task_id,
                success=source == "good",
                mode="test",
                checks=[CheckResult(name="semantic_probe", passed=source == "good")],
            )

    selected = task().model_copy(update={"partition": partition})
    record = await Learner(FixtureGateway(), Evaluator(), tmp_path).attempt(
        selected, "run", "worker", 1, "pool"
    )
    assert record.result.success
    assert record.initial_result is not None and not record.initial_result.success
    assert requires_browser(selected) == (
        partition in (Partition.DEVELOPMENT, Partition.CALIBRATION, Partition.DEMONSTRATION)
    )


@pytest.mark.asyncio
async def test_episode_timeout_during_provider_request_is_not_a_worker_failure(tmp_path):
    class Gateway(FixtureGateway):
        async def complete(self, *args, **kwargs):
            raise TimeoutError("in-flight provider outcome unknown")

    record = await Learner(Gateway(), FixtureEvaluator(), tmp_path).attempt(task(), "timeout", "a", 1, "pool")
    assert record.status == "infrastructure_error"
    assert record.infrastructure_kind == "provider"
    assert record.result is None

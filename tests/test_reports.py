import pytest

from herd.reports import build_report
from herd.schemas import AttemptRecord, BehaviorResult, CheckResult


def attempt(arm, task, success, repeat="repeat-0", cost=0.1):
    return AttemptRecord(
        run_id=f"{arm}-{task}-{repeat}",
        task_id=task,
        learner_id=repeat,
        round_id=0,
        pool_hash="p",
        arm=arm,
        cost_usd=cost,
        result=BehaviorResult(
            task_id=task, success=success, checks=[CheckResult(name="semantic", passed=success)]
        ),
    )


def test_clustered_paired_difference_and_unmatched():
    records = [
        attempt(arm, task, arm == "admitted_pool")
        for task in ("a", "b")
        for arm in ("admitted_pool", "no_pool")
    ]
    report = build_report("e", "p", records, {"a": "f1", "b": "f2"})
    result = report.comparisons["admitted_pool_minus_no_pool"]
    assert result["difference"] == 1
    assert result["interval_95"] == [1, 1]
    assert result["matched_episodes"] == 2
    assert result["families"] == 2
    assert report.arms["curated_docs"]["success_rate"] is None


def test_unknown_cost_and_empty_not_zero_success():
    report = build_report("e", "p", [attempt("no_pool", "a", False, cost=None)], {"a": "f1"})
    assert not report.arms["no_pool"]["cost_complete"]
    assert any("subtotal" in line for line in report.limitations)
    empty = build_report("e", "p", [], {})
    assert empty.arms["no_pool"]["success_rate"] is None
    assert empty.comparisons["admitted_pool_minus_no_pool"]["difference"] is None


def test_infra_excluded_and_duplicates_rejected():
    record = attempt("no_pool", "a", False)
    record.result.infrastructure_error = "runtime unavailable"
    report = build_report("e", "p", [record], {"a": "f1"})
    assert report.arms["no_pool"]["evaluated"] == 0
    assert report.arms["no_pool"]["infrastructure_errors"] == 1
    with pytest.raises(ValueError):
        build_report("e", "p", [record, record], {"a": "f1"})


def test_repeat_identity_not_arrival_order():
    records = [attempt("no_pool", "a", True, "r1"), attempt("admitted_pool", "a", True, "r2")]
    report = build_report("e", "p", records, {"a": "family"})
    assert report.comparisons["admitted_pool_minus_no_pool"]["matched_episodes"] == 0


def test_budget_exhausted_is_a_task_failure_not_pending():
    record = attempt("no_pool", "a", False)
    record.result = None
    record.status = "budget_exhausted"
    report = build_report("e", "p", [record], {"a": "family"})
    assert report.arms["no_pool"]["evaluated"] == 1
    assert report.arms["no_pool"]["pending"] == 0
    assert report.arms["no_pool"]["success_rate"] == 0


def test_first_failure_hook_uses_initial_not_repaired_outcome():
    from herd.reports import first_failure_clusters, calibration_report

    rows = [
        {
            "run_id": str(i),
            "learner_id": f"learner-{i}",
            "round_id": 1,
            "task_id": "t",
            "initial_result": {
                "success": False,
                "checks": [{"name": "structure", "passed": False, "detail": "duplicate"}],
            },
            "result": {"success": True},
            "first_submission_success": False,
            "cost_usd": 0.01,
        }
        for i in (1, 2)
    ]
    clusters = first_failure_clusters(rows)
    assert clusters["clusters"][0]["learner_count"] == 2
    assert clusters["clusters"][0]["check"] == "structure"
    assessment = calibration_report(rows)
    assert assessment["first_submission_failure_rate"] == 1
    assert not assessment["target_is_guarantee"]
    assert assessment["projected_episode_cost_usd"] > 25
    assert assessment["extra_model_calls"]["semantic_curation_max"] == 45


def test_runtime_retry_preserves_matched_repeat():
    retry = attempt("admitted_pool", "a", True, "r:runtime-retry")
    retry.logical_learner_id = "r"
    result = build_report("e", "p", [retry, attempt("no_pool", "a", False, "r")], {"a": "family"})
    assert result.comparisons["admitted_pool_minus_no_pool"]["matched_episodes"] == 1


def test_provider_error_with_prior_behavior_is_not_calibration_failure():
    from herd.reports import calibration_report

    record = attempt("calibration", "a", False)
    record.status = "infrastructure_error"
    assert calibration_report([record])["evaluated"] == 0


def test_calibration_budget_failure_and_retry_spend():
    from herd.reports import calibration_report

    original = attempt("calibration", "a", False)
    original.status = "infrastructure_error"
    retry = attempt("calibration", "a", True, "repeat:retry")
    retry.logical_run_id = original.run_id
    retry.retry_of = original.run_id
    budget = attempt("calibration", "b", False)
    budget.result = None
    budget.status = "budget_exhausted"
    result = calibration_report([original, retry, budget])
    assert result["evaluated"] == 2
    assert result["physical_sessions"] == 3
    assert result["first_submission_failure_rate"] == 1  # fixture helper does not claim first success
    assert result["known_cost_usd"] == pytest.approx(0.3)
    assert result["mean_episode_cost_usd"] == pytest.approx(0.15)
    assert result["cost_complete"]

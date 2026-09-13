import pytest

from herd.reports import build_report
from herd.schemas import AttemptRecord, BehaviorResult, CheckResult


def attempt(arm, task, success, repeat='repeat-0', cost=0.1):
    return AttemptRecord(run_id=f'{arm}-{task}-{repeat}', task_id=task, learner_id=repeat,
                         round_id=0, pool_hash='p', arm=arm, cost_usd=cost,
                         result=BehaviorResult(task_id=task, success=success,
                                               checks=[CheckResult(name='semantic', passed=success)]))


def test_clustered_paired_difference_and_unmatched():
    records = [attempt(arm, task, arm == 'admitted_pool')
               for task in ('a', 'b') for arm in ('admitted_pool', 'no_pool')]
    report = build_report('e', 'p', records, {'a': 'f1', 'b': 'f2'})
    result = report.comparisons['admitted_pool_minus_no_pool']
    assert result['difference'] == 1
    assert result['interval_95'] == [1, 1]
    assert result['matched_episodes'] == 2
    assert result['families'] == 2
    assert report.arms['curated_docs']['success_rate'] is None


def test_unknown_cost_and_empty_not_zero_success():
    report = build_report('e', 'p', [attempt('no_pool', 'a', False, cost=None)], {'a': 'f1'})
    assert not report.arms['no_pool']['cost_complete']
    assert any('subtotal' in line for line in report.limitations)
    empty = build_report('e', 'p', [], {})
    assert empty.arms['no_pool']['success_rate'] is None
    assert empty.comparisons['admitted_pool_minus_no_pool']['difference'] is None


def test_infra_excluded_and_duplicates_rejected():
    record = attempt('no_pool', 'a', False)
    record.result.infrastructure_error = 'runtime unavailable'
    report = build_report('e', 'p', [record], {'a': 'f1'})
    assert report.arms['no_pool']['evaluated'] == 0
    assert report.arms['no_pool']['infrastructure_errors'] == 1
    with pytest.raises(ValueError):
        build_report('e', 'p', [record, record], {'a': 'f1'})


def test_repeat_identity_not_arrival_order():
    records = [attempt('no_pool', 'a', True, 'r1'), attempt('admitted_pool', 'a', True, 'r2')]
    report = build_report('e', 'p', records, {'a': 'family'})
    assert report.comparisons['admitted_pool_minus_no_pool']['matched_episodes'] == 0


def test_budget_exhausted_is_a_task_failure_not_pending():
    record = attempt('no_pool', 'a', False)
    record.result = None
    record.status = 'budget_exhausted'
    report = build_report('e', 'p', [record], {'a': 'family'})
    assert report.arms['no_pool']['evaluated'] == 1
    assert report.arms['no_pool']['pending'] == 0
    assert report.arms['no_pool']['success_rate'] == 0

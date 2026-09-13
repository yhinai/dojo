"""Deterministic, family-clustered summaries of frozen fresh-worker results."""
import random
import re
from collections import defaultdict
from datetime import datetime
from statistics import mean

from herd.schemas import AttemptRecord, ExperimentReport

ARMS = ('no_pool', 'curated_docs', 'raw_memory', 'admitted_pool')


def build_report(experiment_id: str, pool_hash: str, attempts: list[AttemptRecord],
                 family_by_task: dict[str, str], status: str = 'complete') -> ExperimentReport:
    if len({a.run_id for a in attempts}) != len(attempts):
        raise ValueError('duplicate worker run IDs')
    if any(a.task_id not in family_by_task for a in attempts):
        raise ValueError('every task requires a declared family')
    modes = {a.mode for a in attempts}
    if len(modes) > 1:
        raise ValueError('cannot mix fixture and measured attempts')
    report = ExperimentReport(experiment_id=experiment_id, pool_hash=pool_hash, status=status,
                              mode=next(iter(modes), 'measured'))
    report.limitations = ['Intervals resample task families, not individual episodes; descriptive for this task set.',
                          'One learned pool does not establish repeatability of the entire learning process.',
                          'Costs cover supplied final-evaluation attempts; total learning/gating spend is reported separately by the experiment ledger.']
    valid_by_arm = {}
    for arm in ARMS:
        records = [a for a in attempts if a.arm == arm]
        valid = [a for a in records if (a.result is not None and not a.result.infrastructure_error)
                 or (a.result is None and a.status in {'budget_exhausted', 'timeout', 'failed'})]
        valid_by_arm[arm] = valid
        known = [a.cost_usd for a in records if a.cost_usd is not None]
        report.arms[arm] = {
            'allocated': len(records), 'evaluated': len(valid),
            'infrastructure_errors': sum(bool(a.result and a.result.infrastructure_error) for a in records),
            'pending': sum(a.result is None and a.status not in {'budget_exhausted', 'timeout', 'failed'} for a in records),
            'successes': sum(bool(a.result and a.result.success) for a in valid),
            'success_rate': mean(bool(a.result and a.result.success) for a in valid) if valid else None,
            'first_submission_rate': mean(a.first_submission_success for a in valid) if valid else None,
            'input_tokens': sum(a.input_tokens for a in records),
            'output_tokens': sum(a.output_tokens for a in records),
            'tool_calls': sum(a.tool_calls for a in records),
            'known_cost_usd': sum(known), 'cost_complete': len(known) == len(records),
            'families': len({family_by_task[a.task_id] for a in valid}),
        }
    report.total_cost_usd = sum(a.cost_usd for a in attempts if a.cost_usd is not None)
    if any(a.cost_usd is None for a in attempts):
        report.limitations.append('Total cost is the known subtotal; some episode prices are unavailable.')
    if any(a.arm not in ARMS for a in attempts):
        report.limitations.append('Non-final arms excluded from arm comparisons; their known costs remain included.')
    # Match repeated trials by their stable learner/repeat identity, never by success or arrival order.
    def keyed(records):
        output = {}
        for a in records:
            key = (a.task_id, a.learner_id)
            if key in output:
                raise ValueError('duplicate task/repeat identity within arm')
            output[key] = a
        return output
    treatment = keyed(valid_by_arm['admitted_pool'])
    for baseline in ARMS[:-1]:
        control = keyed(valid_by_arm[baseline])
        common = sorted(treatment.keys() & control.keys())
        families = defaultdict(list)
        raw = []
        for key in common:
            delta = int(bool(treatment[key].result and treatment[key].result.success)) - int(bool(control[key].result and control[key].result.success))
            families[family_by_task[key[0]]].append(delta)
            raw.append({'task_id': key[0], 'repeat_id': key[1], 'family_id': family_by_task[key[0]],
                        'treatment_run_id': treatment[key].run_id, 'control_run_id': control[key].run_id,
                        'difference': delta})
        ci = None
        if len(families) >= 2:
            rng = random.Random(20260913)
            clusters = [families[k] for k in sorted(families)]
            boot = sorted(mean(x for group in rng.choices(clusters, k=len(clusters)) for x in group)
                          for _ in range(4000))
            ci = [boot[99], boot[3899]]
        report.comparisons[f'admitted_pool_minus_{baseline}'] = {
            'difference': mean(r['difference'] for r in raw) if raw else None,
            'interval_95': ci, 'interval_unit': 'task_family_cluster', 'bootstrap_seed': 20260913,
            'bootstrap_samples': 4000, 'matched_episodes': len(raw), 'families': len(families),
            'unmatched_episodes': len(treatment) + len(control) - 2 * len(common), 'paired_outcomes': raw,
        }
    if not attempts:
        report.limitations.append('No worker results recorded; there is no measured learning estimate.')
    return report


def experiment_accounting(store, experiment_id: str, ledger=None) -> dict:
    """Account once per provider request, including distillation and unresolved charges.

    Episode cost fields are only a fallback when no durable ledger is available.
    Concurrent episode durations are summed separately from elapsed experiment time.
    """
    attempts = store.list(experiment_id, 'attempt')
    tasks = {t['task_id']: t for t in store.list(experiment_id, 'task')}
    by_run = {a['run_id']: a for a in attempts}
    stages = {name: {'requests': 0, 'known_cost_usd': 0.0, 'unresolved_requests': 0,
                     'reserved_unknown_usd': 0.0, 'episode_seconds': 0.0, 'episodes': 0}
              for name in ('development', 'repair', 'distillation', 'curation', 'admission', 'regression',
                           'final', 'demonstration', 'calibration', 'other')}

    def stage_for(attempt):
        return tasks.get(attempt['task_id'], {}).get('partition', 'other')

    def seconds(start, end):
        try:
            return max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
        except (ValueError, TypeError):
            return None

    for attempt in attempts:
        row = stages.setdefault(stage_for(attempt), stages['other'].copy())
        row['episodes'] += 1
        duration = seconds(attempt.get('started_at'), attempt.get('completed_at'))
        if duration is not None:
            row['episode_seconds'] += duration
    entries = ledger.entries(list(by_run)) if ledger is not None else []
    for entry in entries:
        run_id = next((key for key in sorted(by_run, key=len, reverse=True)
                       if entry['request_id'].startswith(key + ':')), None)
        attempt = by_run.get(run_id)
        if attempt is None:
            continue
        logical_id = re.sub(r':retry:\d+$', '', entry['request_id'])
        stage = 'distillation' if logical_id.endswith(':distill') else stage_for(attempt)
        if ':curation:' in logical_id:
            stage = 'curation'
        # First model response creates the initial submission. Subsequent responses
        # may inspect or repair it, so request-level classification is conservative.
        if stage == 'development' and ':turn:' in logical_id:
            turn = int(logical_id.rsplit(':turn:', 1)[1])
            if turn > 0:
                stage = 'repair'
        row = stages.setdefault(stage, stages['other'].copy())
        row['requests'] += 1
        if entry.get('charged') is None:
            row['unresolved_requests'] += 1
            row['reserved_unknown_usd'] += entry['reserved']
        else:
            row['known_cost_usd'] += entry['charged']
    if ledger is None:
        for attempt in attempts:
            row = stages.setdefault(stage_for(attempt), stages['other'].copy())
            if attempt.get('cost_usd') is not None:
                row['known_cost_usd'] += attempt['cost_usd']
            else:
                row['unresolved_requests'] += 1
    experiment = store.get(experiment_id, 'experiment', experiment_id, {})
    events = store.events(experiment_id)
    last_time = events[-1]['observed_at'] if events else experiment.get('created_at')
    unresolved = sum(row['unresolved_requests'] for row in stages.values())
    known = sum(row['known_cost_usd'] for row in stages.values())
    return {'source': 'provider_request_ledger' if ledger is not None else 'episode_subtotal',
            'stages': stages, 'known_cost_usd': known,
            'total_cost_usd': known if ledger is not None and not unresolved else None,
            'unresolved_requests': unresolved,
            'reserved_unknown_usd': sum(row['reserved_unknown_usd'] for row in stages.values()),
            'cost_complete': ledger is not None and not unresolved,
            'elapsed_seconds': seconds(experiment.get('created_at'), last_time),
            'episode_seconds': sum(row['episode_seconds'] for row in stages.values()),
            'notes': ['Repair includes development model turns after the first; inspection turns may be included.',
                      'Elapsed time includes pauses; summed episode time overlaps during concurrent execution.',
                      'Hosting, ARIA, and unmetered external charges are excluded.',
                      'Missing ledger means separate distillation costs are unavailable.']}


def attach_accounting(report: ExperimentReport, accounting: dict) -> ExperimentReport:
    report.comparisons['experiment_accounting'] = accounting
    report.total_cost_usd = accounting['known_cost_usd']
    report.limitations = [line for line in report.limitations if not line.startswith('Costs cover supplied')]
    if not accounting['cost_complete']:
        report.limitations.append('Experiment cost is a known subtotal; unresolved billing is explicitly retained.')
    return report

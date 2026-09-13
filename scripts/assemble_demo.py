"""Assemble authentic, predetermined demonstration evidence; never execute a model.

Usage: uv run python scripts/assemble_demo.py EXPERIMENT_ID --task-id TASK_ID
A declared task ID is required. Missing assets remain pending, never substituted.
"""
import argparse
import json
from pathlib import Path

from herd.schemas import digest, utcnow
from herd.store import Store


def assemble(store: Store, experiment_id: str, task_id: str, directory: Path) -> dict:
    experiment = store.get(experiment_id, 'experiment', experiment_id)
    if not experiment:
        raise ValueError('Unknown experiment')
    tasks = {t['task_id']: t for t in store.list(experiment_id, 'task')}
    task = tasks.get(task_id)
    if not task or task.get('partition') != 'demonstration':
        raise ValueError('Choose a registered demonstration-partition task before looking at its outcomes')
    attempts = store.list(experiment_id, 'attempt')
    if any(a.get('mode', 'measured') != 'measured' for a in attempts):
        raise ValueError('Fixture and measured experiments cannot be used together for the demo')
    selected = [a for a in attempts if a['task_id'] == task_id]
    by_repeat = {}
    for attempt in selected:
        by_repeat.setdefault(attempt['learner_id'], {})[attempt['arm']] = attempt
    # Predetermined stable ordering; do not seek a flattering outcome.
    repeat = min(by_repeat) if by_repeat else None
    pair = by_repeat.get(repeat, {})
    pending = []
    if not all(arm in pair for arm in ('no_pool', 'admitted_pool')):
        pending.append('Predetermined demonstration task needs two independent fresh workers: no_pool and admitted_pool.')
    lessons = store.list(experiment_id, 'lesson')
    gates = store.list(experiment_id, 'gate')
    report = store.get(experiment_id, 'report', 'current')
    events = store.events(experiment_id)
    if not lessons:
        pending.append('No recorded lesson available for repair-to-memory beat.')
    if not gates:
        pending.append('No admission stream available for gate beat.')
    if not report:
        pending.append('Final four-arm report has not been produced.')
    if not any('aria' in e['event_type'] for e in events):
        pending.append('Authentic ARIA analysis not attached.')
    pending.extend(['Live slider probe and exact port must be rehearsed.',
                    'Three-minute recording and under-two-minute submission video not produced by this script.'])
    bundle = {'schema': 'herd-demo-v1', 'experiment_id': experiment_id, 'created_at': utcnow(),
              'mode': 'measured_evidence_replay', 'task_selection': 'explicit_task_id_not_outcome_selected',
              'task': task, 'experiment': experiment, 'demonstration_pair': pair,
              'attempts': attempts, 'lessons': lessons, 'gates': gates,
              'pairs': store.list(experiment_id, 'pair'), 'pools': store.list(experiment_id, 'pool'),
              'events': events, 'report': report, 'pending': pending}
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for arm, attempt in pair.items():
        source = attempt.get('source', '')
        if source:
            # Safe output name from content identity, not an arbitrary database arm string.
            path = directory / f'notebook-{digest(arm)[:12]}.py'
            path.write_text(source)
            artifacts[arm] = {'path': path.name, 'source_hash': digest(source), 'run_id': attempt['run_id']}
    bundle['notebook_artifacts'] = artifacts
    bundle['bundle_hash'] = digest(bundle)
    (directory / 'manifest.json').write_text(json.dumps(bundle, indent=2))
    return bundle


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment_id')
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--state-dir', type=Path, default=Path('experiments'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/demo'))
    args = parser.parse_args()
    result = assemble(Store(args.state_dir / 'herd.sqlite3'), args.experiment_id, args.task_id, args.output)
    print(json.dumps({'manifest': str(args.output / 'manifest.json'), 'pending': result['pending']}, indent=2))

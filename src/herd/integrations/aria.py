"""Authentic manual ARIA handoff. No undocumented automated ARIA endpoint."""
import json
from pathlib import Path
from urllib.parse import urlparse

from herd.schemas import digest, utcnow


def export_bundle(experiment_id: str, development_summary: dict, directory: str | Path) -> Path:
    if development_summary.get('partition') != 'development':
        raise ValueError('ARIA curriculum analysis accepts development-only summaries')
    bundle = {'experiment_id': experiment_id, 'created_at': utcnow(),
              'summary': development_summary, 'summary_hash': digest(development_summary),
              'workflow': 'manual_aria_interface',
              'request': 'Analyze these recorded development results. Cite evidence IDs. Identify recurring failures, '
                         'ambiguous lessons and underrepresented tracks. Suggest a development-only curriculum action. '
                         'Do not use final or admission outcomes to choose tasks.'}
    destination = Path(directory) / f'{digest(experiment_id)[:16]}-aria-input.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(bundle, indent=2))
    return destination


def import_analysis(bundle_path: str | Path, report_text: str, source_url: str,
                    operator: str, curriculum_action: str, corrections: str = '') -> dict:
    source = urlparse(source_url)
    if source.scheme != 'https' or not (source.hostname == 'wandb.ai' or (source.hostname or '').endswith('.wandb.ai')):
        raise ValueError('provide the authentic HTTPS W&B ARIA report URL')
    if not all(value.strip() for value in (report_text, operator, curriculum_action)):
        raise ValueError('report, operator attribution, and concrete curriculum action are required')
    bundle = json.loads(Path(bundle_path).read_text())
    if digest(bundle['summary']) != bundle['summary_hash']:
        raise ValueError('analysis input bundle was modified')
    record = {'experiment_id': bundle['experiment_id'], 'input_hash': bundle['summary_hash'],
              'report': report_text, 'report_hash': digest(report_text), 'source_url': source_url,
              'operator': operator, 'curriculum_action': curriculum_action, 'corrections': corrections,
              'verification': 'operator_attested_manual_import', 'imported_at': utcnow()}
    destination = Path(bundle_path).with_suffix('.analysis.json')
    destination.write_text(json.dumps(record, indent=2))
    return record

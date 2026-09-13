import json
import os
from pathlib import Path

from herd.schemas import digest

ROOT = Path(__file__).resolve().parents[2]
RAW_RULE = "first verified repair per learner per round; chronological; public lesson text; tag overlap; token cap 2000; frozen-v1"


def load_environment():
    """Load local configuration and explicitly named secret files, never print values."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    for name in ('WANDB_API_KEY', 'HERD_INFERENCE_API_KEY', 'HERD_CONTROL_TOKEN', 'HERD_API_BASIC_PASSWORD'):
        secret_file = os.getenv(name + '_FILE')
        if secret_file:
            path = Path(secret_file)
            if not path.is_file() or path.stat().st_mode & 0o007:
                raise ValueError(f'{name}_FILE must be an existing file inaccessible to other users')
            secret = path.read_text().strip()
            if not secret:
                raise ValueError(f'{name}_FILE is empty')
            os.environ[name] = secret


def provider_capabilities():
    """A neutral gateway contract; sponsor identity alone does not imply compatibility."""
    provider = os.getenv('HERD_PROVIDER_NAME', 'W&B Inference')
    custom = os.getenv('HERD_INFERENCE_BASE_URL', 'https://api.inference.wandb.ai/v1')
    return {'provider': provider, 'protocol': 'openai_chat_completions',
            'base_url': custom, 'required_response_fields': ['choices[0].message.content',
                                                          'usage.prompt_tokens', 'usage.completion_tokens'],
            'typesafe': {'status': 'operator_configured_adapter' if provider.lower() == 'typesafe'
                        else 'available_through_verified_compatible_provider',
                        'requirement': 'Supply the sponsor-documented HTTPS endpoint, model and token pricing; '
                                       'run provider-check before creating an experiment.'},
            'molab': {'status': 'deployment_bundle_available',
                      'requirement': 'Import app/control_room.py with the herd package and reachable authenticated API. '
                                     'Hosted execution requires operator access; no deployment is claimed.'}}


def configuration():
    protocol = json.loads((ROOT / "claude/protocol.json").read_text())
    return {
        "protocol": protocol,
        "protocol_hash": digest(protocol),
        "runtime_hash": digest(
            {
                name: (ROOT / name).read_text()
                for name in [
                    "uv.lock",
                    "Dockerfile",
                    "src/herd/task_registry.py",
                    "src/herd/adapters/runner.py",
                    "src/herd/adapters/runtime.py",
                    "src/herd/adapters/browser_oracle.py",
                ]
            }
        ),
        "docs_hash": digest((ROOT / "docs/snapshots/marimo.md").read_text()),
        "curated_docs_hash": digest((ROOT / "docs/snapshots/curated-marimo.md").read_text()),
        "raw_rule_hash": digest(RAW_RULE),
    }

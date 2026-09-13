"""Export a standalone marimo control room; no credentials or experiment state included."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(destination: Path):
    destination.mkdir(parents=True, exist_ok=False)
    source = (ROOT / 'app/control_room.py').read_text()
    original = '    from herd.config import load_environment as _load_environment\n    _load_environment()'
    if original not in source:
        raise ValueError('Dashboard environment loader changed; review packaging transform')
    source = source.replace(original, '    from dotenv import load_dotenv as _load_dotenv\n    _load_dotenv()')
    (destination / 'control_room.py').write_text(source)
    (destination / 'requirements.txt').write_text('marimo==0.24.2\nhttpx==0.28.1\npython-dotenv==1.2.3\n')
    (destination / 'SETUP.md').write_text(
        '# HERD molab control room\n\n'
        'Upload control_room.py and requirements.txt using the molab file browser. '
        'Install the listed dependencies with the notebook package manager. '
        'Set HERD_API_URL to your deployed HTTPS API, HERD_CONTROL_TOKEN to its token, '
        'and HERD_DEMO_MODE=1 in the notebook Secrets panel. For the supplied Caddy proxy, '
        'also configure HERD_API_BASIC_USER and HERD_API_BASIC_PASSWORD. '
        'Keep this authenticated notebook private. No inference keys belong here.\n\n'
        'The notebook reads live API evidence; the scheduler and Docker sandbox stay on your dedicated host. '
        'Uploaded notebook files persist according to molab storage rules; generated local artifacts are not '
        'used as primary durable storage. Do not claim a hosted deployment until the notebook opens and '
        'authenticates successfully.\n\n'
        'Official storage and Secrets documentation: https://marimo.io/pages/molab/storage\n')
    manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in destination.iterdir()}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    arguments = parser.parse_args()
    print(json.dumps(package(arguments.destination), indent=2))

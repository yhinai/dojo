"""Validate the actual Caddy configuration with the official runtime (no public listener)."""
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
image = os.getenv('HERD_CADDY_IMAGE', 'caddy:2')
hashed = subprocess.check_output(['docker', 'run', '--rm', image, 'caddy', 'hash-password',
                                  '--plaintext', 'verification-only-not-a-deployment-secret'], text=True).strip()
subprocess.run(['docker', 'run', '--rm', '--network', 'none',
                '-e', 'HERD_HOST=localhost', '-e', 'HERD_OPERATOR=verification',
                '-e', f'HERD_PASSWORD_HASH={hashed}',
                '-v', f'{root / "deploy/Caddyfile"}:/etc/caddy/Caddyfile:ro',
                image, 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile'], check=True)

#!/bin/sh
# Run as root on a dedicated Linux host after uv, Docker and Caddy are installed.
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Run as root'; exit 1; }
[ -f /opt/herd/pyproject.toml ] || { echo 'Clone the complete repository to /opt/herd first'; exit 1; }
command -v uv >/dev/null
command -v docker >/dev/null
command -v caddy >/dev/null
id herd >/dev/null 2>&1 || useradd --system --home /var/lib/herd --create-home herd
usermod -aG docker herd
install -d -o herd -g herd -m 0700 /var/lib/herd
install -d -o root -g herd -m 0750 /etc/herd /etc/herd/secrets
cd /opt/herd
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
uv sync --frozen --extra weave --python /usr/bin/python3
PLAYWRIGHT_BROWSERS_PATH=/opt/herd/browsers .venv/bin/playwright install --with-deps chromium
docker build -t herd-runtime:local .
install -m 0644 deploy/herd-api.service deploy/herd-dashboard.service /etc/systemd/system/
install -o herd -g herd -m 0644 app/control_room.py /var/lib/herd/control_room.py
install -d /etc/systemd/system/caddy.service.d
install -m 0644 deploy/caddy-environment.conf /etc/systemd/system/caddy.service.d/herd.conf
[ -f /etc/herd/herd.env ] || install -o root -g herd -m 0640 deploy/herd.env.example /etc/herd/herd.env
[ -f /etc/herd/proxy.env ] || install -o root -g root -m 0600 deploy/proxy.env.example /etc/herd/proxy.env
systemctl daemon-reload
echo 'Installed. Configure /etc/herd/herd.env, /etc/herd/proxy.env and secrets; then enable services.'
echo 'Services were not started and no public port was opened.'

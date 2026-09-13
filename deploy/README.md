# Dedicated single-operator deployment

This package hosts the complete scheduler and marimo control room on one Linux machine. It preserves the full five-learner protocol while bounding parallel Docker workers. It is not a multi-tenant service. The runtime can execute hostile generated notebooks, so deploy on a dedicated host; the API operator's Docker group is effectively host-administrator access.

## Install

Use Linux with systemd, system Python 3.11+, a running Docker Engine, uv and Caddy 2.8+. Clone the **complete checkout** into `/opt/herd`; runtime bindings depend on source files, the protocol and `uv.lock`, so a standalone wheel is insufficient. Run `sudo sh /opt/herd/deploy/install.sh`. The installer verifies Docker reachability before changing host state, then builds the candidate runtime, installs Chromium, locked editable application dependencies, service units and a Caddy environment override. It does not start services or open public ports. The system interpreter prevents a virtualenv from referring to a root-only managed Python path.

Configure `/etc/herd/herd.env` and secret files with owner `root:herd`, mode `0640`. The control token is required for mutations and private evidence reads. Choose `HERD_MAX_WORKERS` between 1 and 10; default 4 retains all five learners with queued work. Allow at least 512 MiB per active notebook plus browser/API overhead; use 2 workers on a small host. State lives in `/var/lib/herd`, including every SQLite database, reservations, uploads and workspace artifact. Neither generated notebook containers nor exported presentation files receive credentials.

The dashboard runs a copy in `/var/lib/herd/control_room.py` to allow marimo's local cache without making `/opt/herd` writable. Re-run the installer after updates to refresh this copy. Service definitions set non-root users, restrictive umasks and filesystem protections. Logs are in journald.

## Authenticate and start

The installer creates `/etc/herd/proxy.env` from `deploy/proxy.env.example` with mode `0600`. Replace its placeholders: generate a bcrypt hash with `caddy hash-password`, then set `HERD_PASSWORD_HASH`, `HERD_OPERATOR`, and `HERD_HOST=your-dns-name`. This file is consumed by the installed Caddy service override. Caddy's [`basic_auth`](https://caddyserver.com/docs/caddyfile/directives/basic_auth) requires a hash and protects the dashboard, API and WebSocket upgrades. Backend read protection independently checks `X-HERD-Token`.

Copy `/opt/herd/deploy/Caddyfile` to `/etc/caddy/Caddyfile`. Preserve an existing site's configuration if sharing a machine; this package assumes a dedicated host. Validate using the actual configured environment before activating:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now herd-api herd-dashboard
# Caddy's systemd process reads /etc/herd/proxy.env.
sudo systemctl restart caddy
sudo systemctl status herd-api herd-dashboard caddy
```

The API listens on loopback port 8000 and the dashboard on loopback 2718. Only Caddy should listen publicly. Configure DNS and firewall for HTTPS before sharing the URL. Caddy manages certificates for a reachable public DNS name. Verify anonymous requests receive 401, sign-in works, the dashboard refreshes, and its mutation controls use the configured token. Do not put control tokens in URLs. From the host, `curl --fail http://127.0.0.1:8000/api/health` gives minimal liveness. An external monitor must authenticate to the proxy; `journalctl -u herd-api -u herd-dashboard` contains process failures. Use `herd health` and `herd accounting EXPERIMENT_ID` for durable integrity/cost checks.

## Back up and restore

Pause the experiment and wait for its worker checkpoint, then stop **both** services and any manual `herd run`, `sync-weave`, or billing command. CLI/API hold shared maintenance leases; backup requires exclusive maintenance, scheduler and evidence locks. This prevents cross-database snapshots while a service or writer is active.

```sh
uv run herd control EXPERIMENT_ID pause
sudo systemctl stop herd-api herd-dashboard
# Run with the same HERD_STATE_DIR=/var/lib/herd and secret environment as the service.
uv run herd backup /secure-backups/herd-2026-09-13
uv run herd restore /secure-backups/herd-2026-09-13 /var/lib/herd-restored
```

Backup includes SQLite-consistent snapshots of state, budget and outbox databases and workspace files, plus SHA-256 checksums. It excludes `.env`, `secrets`, locks and symlinks. Store secrets separately in your secret manager. Copy backups off-host with access controls. Restore verifies every checksum, database and event chain in a staging directory, then atomically renames into a **new** destination; it never replaces existing state. After stopping services, update `HERD_STATE_DIR` and service `ReadWritePaths` to the restored path, ensure `herd` owns it, and restart. Never run original and restored copies simultaneously: a backup is a recovery point, not permission to duplicate billed experiment work.

## Verify package without external accounts

```sh
sh -n deploy/install.sh
uv run pytest tests/test_delivery.py tests/test_integrations.py tests/test_ops.py -q
python3 deploy/verify_proxy.py
```

The proxy check runs official Caddy in a container with networking disabled and validates configuration without creating a public listener. The Linux CI job also runs `systemd-analyze verify`. On macOS, Linux service activation is not executable; real local API startup, authentication, maintenance exclusion, backup/restore and proxy validation are checked independently. Hosting activation, TLS issuance and actual sponsor accounts remain operator setup.

## molab

Create a standalone artifact with `uv run python scripts/package_molab.py /new/output/directory`. Upload its control room and requirements through the molab file browser; its setup file documents API and secret configuration. It uses the same dashboard against the durable hosted backend, not an in-memory replacement scheduler. Official molab [storage documentation](https://marimo.io/pages/molab/storage) describes uploaded file persistence and Secrets. A successful hosted session and its URL are execution evidence that must be collected with account access.

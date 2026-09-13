import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

from herd.backup import backup_state, restore_state
from herd.config import ROOT, load_environment
from herd.gateway import BudgetLedger
from herd.reports import experiment_accounting
from herd.store import Store


def test_all_stage_accounting_includes_distillation_and_unknown(tmp_path):
    store = Store(tmp_path / 'herd.sqlite3')
    store.put('e', 'experiment', 'e', {'id': 'e', 'created_at': '2026-09-13T00:00:00+00:00'})
    store.put('e', 'task', 't', {'task_id': 't', 'partition': 'development'})
    store.put('e', 'attempt', 'run', {'run_id': 'run', 'task_id': 't', 'cost_usd': .1,
                                   'started_at': '2026-09-13T00:00:00+00:00',
                                   'completed_at': '2026-09-13T00:00:02+00:00'})
    ledger = BudgetLedger(tmp_path / 'budget.sqlite3', 10)
    for request, reserved, settled in [('run:turn:0', .2, .1), ('run:turn:1', .2, .15),
                                        ('run:distill', .4, .3), ('run:curation:hash', .5, None),
                                        ('run-other:turn:0', 1, 1)]:
        ledger.reserve(request, reserved)
        if settled is not None:
            ledger.settle(request, settled)
    report = experiment_accounting(store, 'e', ledger)
    assert report['known_cost_usd'] == pytest.approx(.55)
    assert report['stages']['distillation']['known_cost_usd'] == .3
    assert report['stages']['repair']['known_cost_usd'] == .15
    assert report['stages']['curation']['unresolved_requests'] == 1
    assert report['reserved_unknown_usd'] == .5
    assert report['total_cost_usd'] is None
    assert report['episode_seconds'] == 2


def test_retried_requests_keep_original_stage_and_all_charges(tmp_path):
    store = Store(tmp_path / 'herd.sqlite3')
    store.put('e', 'task', 't', {'task_id': 't', 'partition': 'development'})
    store.put('e', 'attempt', 'run', {'run_id': 'run', 'task_id': 't'})
    ledger = BudgetLedger(tmp_path / 'budget.sqlite3', 10)
    for request in ('run:turn:0', 'run:turn:0:retry:1', 'run:distill:retry:1', 'run:curation:hash:retry:1'):
        ledger.reserve(request, .1)
        ledger.settle(request, .1)
    result = experiment_accounting(store, 'e', ledger)
    assert result['known_cost_usd'] == pytest.approx(.4)
    assert result['stages']['development']['known_cost_usd'] == pytest.approx(.2)
    assert result['stages']['repair']['known_cost_usd'] == 0
    assert result['stages']['distillation']['known_cost_usd'] == .1
    assert result['stages']['curation']['known_cost_usd'] == .1


def test_full_backup_restore_preserves_three_databases_and_artifacts(tmp_path):
    source = tmp_path / 'state'
    store = Store(source / 'herd.sqlite3')
    store.put('e', 'experiment', 'e', {'id': 'e', 'status': 'paused'})
    budget = BudgetLedger(source / 'budget.sqlite3', 10)
    budget.reserve('request', .5)
    from herd.integrations.weave import WeaveIntegration
    weave = WeaveIntegration(None, source)
    weave.enqueue('pool', 'key', {'pool_hash': 'hash'})
    (source / 'workspaces').mkdir()
    (source / 'workspaces' / 'notebook.py').write_text('print(42)')
    (source / '.env').write_text('NEVER_COPY=secret')
    manifest = backup_state(source, tmp_path / 'backup')
    assert '.env' not in manifest['files']
    result = restore_state(tmp_path / 'backup', tmp_path / 'restore')
    assert result['restored']
    restored = Store(tmp_path / 'restore' / 'herd.sqlite3')
    assert restored.verify_events('e')
    assert BudgetLedger(tmp_path / 'restore' / 'budget.sqlite3', 10).summary()['pending_requests'] == 1
    assert WeaveIntegration(None, tmp_path / 'restore').status()[0]['status'] == 'pending'
    assert (tmp_path / 'restore' / 'workspaces' / 'notebook.py').read_text() == 'print(42)'
    with pytest.raises(ValueError):
        restore_state(tmp_path / 'backup', source)
    (tmp_path / 'backup' / 'workspaces' / 'notebook.py').write_text('tampered')
    with pytest.raises(ValueError, match='checksum'):
        restore_state(tmp_path / 'backup', tmp_path / 'corrupt')


def test_backup_refuses_running_and_locked_state(tmp_path):
    store = Store(tmp_path / 'state' / 'herd.sqlite3')
    store.put('e', 'experiment', 'e', {'id': 'e', 'status': 'running'})
    with pytest.raises(ValueError, match='Pause'):
        backup_state(tmp_path / 'state', tmp_path / 'backup')
    store.put('e', 'experiment', 'e', {'id': 'e', 'status': 'paused'})
    with store.execution_lock(), pytest.raises(ValueError, match='scheduler'):
        backup_state(tmp_path / 'state', tmp_path / 'backup')


def test_secret_file_loader(tmp_path, monkeypatch):
    secret = tmp_path / 'token'
    secret.write_text('private-control-token')
    secret.chmod(0o600)
    monkeypatch.setenv('HERD_CONTROL_TOKEN_FILE', str(secret))
    monkeypatch.delenv('HERD_CONTROL_TOKEN', raising=False)
    load_environment()
    assert os.environ['HERD_CONTROL_TOKEN'] == 'private-control-token'
    secret.chmod(0o644)
    with pytest.raises(ValueError, match='inaccessible'):
        load_environment()


def test_real_cli_service_health_and_read_protection(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    environment = {**os.environ, 'HERD_STATE_DIR': str(tmp_path / 'state'),
                   'HERD_CONTROL_TOKEN': 'test-delivery-control-token', 'HERD_AUTH_READS': '1'}
    environment.pop('HERD_CONTROL_TOKEN_FILE', None)
    process = subprocess.Popen([sys.executable, '-m', 'herd.cli', 'serve', '--demo', '--port', str(port)],
                               cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f'http://127.0.0.1:{port}/api/health', timeout=1)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        else:
            pytest.fail('Real CLI server did not become healthy')
        assert httpx.get(f'http://127.0.0.1:{port}/api/experiments').status_code == 401
        response = httpx.get(f'http://127.0.0.1:{port}/api/experiments',
                             headers={'X-HERD-Token': 'test-delivery-control-token'})
        assert response.status_code == 200
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_deployment_shell_and_entrypoints():
    subprocess.run(['sh', '-n', str(ROOT / 'deploy/install.sh')], check=True)
    subprocess.run([sys.executable, '-m', 'herd.cli', '--help'], check=True, capture_output=True)
    assert 'basic_auth' in (ROOT / 'deploy/Caddyfile').read_text()
    for filename in ('herd-api.service', 'herd-dashboard.service'):
        service = (ROOT / 'deploy' / filename).read_text()
        assert 'User=herd' in service and 'UMask=0077' in service
        assert '/opt/herd' in service

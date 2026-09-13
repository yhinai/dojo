from concurrent.futures import ThreadPoolExecutor

import pytest

from herd.gateway import BudgetLedger, GatewayError
from herd.store import Store


def test_slots_atomic_updates_restart_and_backup(tmp_path):
    path = tmp_path / "state.db"
    stores = [Store(path), Store(path)]
    with ThreadPoolExecutor(2) as pool:
        slots = list(pool.map(lambda i: stores[i % 2].allocate_slot("e", str(i)), range(15)))
    assert len(set(slots)) == 15
    assert Store(path).allocate_slot("e", "2") == slots[2]
    with pytest.raises(ValueError, match="exhausted"):
        stores[0].allocate_slot("e", "extra")
    store = stores[0]
    store.put("e", "gate", "g", {"pairs": []})
    with pytest.raises(ValueError):
        store.atomic_updates(
            "e", [("pair", "p", {"success": True}), ("gate", "g", {"pairs": ["p"]})], [("gate", "g", {})]
        )
    assert store.get("e", "pair", "p") is None
    store.atomic_updates(
        "e",
        [("pair", "p", {"success": True}), ("gate", "g", {"pairs": ["p"]})],
        [("gate", "g", {"pairs": []})],
    )
    backup = Store(store.backup(tmp_path / "backup.db"))
    assert backup.get("e", "gate", "g") == {"pairs": ["p"]}
    assert backup.verify_events("e")


def test_execution_lock_and_durable_commands(tmp_path):
    a, b = Store(tmp_path / "a.db"), Store(tmp_path / "a.db")
    with a.execution_lock(), pytest.raises(RuntimeError, match="Another scheduler"), b.execution_lock():
        pass
    with b.execution_lock():
        pass
    a.put("e", "experiment", "e", {"id": "e", "status": "running"})
    a.request_control("e", "pause")
    assert b.control("e")["action"] == "pause"
    b.request_control("e", "cancel")
    with pytest.raises(ValueError, match="terminal"):
        a.request_control("e", "resume")


def test_billing_reconciliation_audit_requires_evidence(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.db", 1)
    ledger.reserve("run:turn:0", 0.1)
    with pytest.raises(ValueError):
        ledger.reconcile("run:turn:0", 0, "", "operator")
    assert ledger.summary()["committed_usd"] == 0.1
    record = ledger.reconcile("run:turn:0", 0.02, "Provider invoice INV-123 request abc", "operator")
    assert record["actual_usd"] == 0.02
    assert ledger.summary(["run"])["pending_requests"] == 0
    assert ledger.summary(["other"])["committed_usd"] == 0
    with pytest.raises(GatewayError):
        ledger.reconcile("run:turn:0", 0, "Provider invoice INV-123", "operator")
    with ledger._connect() as db:
        assert db.execute("SELECT count(*) FROM inference_reconciliations").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_cancel_runtime_reaps_process(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path

    from herd.adapters.runtime import RuntimeEvaluator
    from herd.schemas import Partition
    from herd.task_registry import TaskRegistry

    registry = TaskRegistry("runtime", "docs")
    task = registry.generate(Partition.CALIBRATION, 91)
    runtime = RuntimeEvaluator(registry, mode="trusted-reference")
    real_create = asyncio.create_subprocess_exec
    processes = []

    async def hanging(*args, **kwargs):
        import sys

        process = await real_create(sys.executable, "-c", "import time; time.sleep(300)", **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", hanging)
    execution = asyncio.create_task(runtime.evaluate(task, registry.reference_source(task), Path(tmp_path)))
    for _ in range(100):
        if processes:
            break
        await asyncio.sleep(0.01)
    assert processes
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(execution, 5)
    assert processes[0].returncode is not None


def test_maintenance_lock_blocks_backup_and_service(tmp_path):
    import fcntl

    store = Store(tmp_path / "state.db")
    with store.maintenance_lock(), (tmp_path / "maintenance.lock").open("a+") as handle:
        with pytest.raises(BlockingIOError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    with (tmp_path / "maintenance.lock").open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="maintenance"):
            with store.maintenance_lock():
                pass

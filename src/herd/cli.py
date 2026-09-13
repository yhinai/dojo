from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import typer

from herd.config import ROOT, configuration, load_environment, provider_capabilities
from herd.store import Store

app = typer.Typer(help="HERD — One agent struggles. Every agent learns.")


@app.callback()
def maintenance_guard(ctx: typer.Context):
    """Hold a shared service lease; offline backups take an exclusive lease."""
    if ctx.invoked_subcommand in {'backup', 'restore'}:
        return
    import fcntl
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / 'maintenance.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise typer.BadParameter('State maintenance is active; retry after backup completes') from None
    ctx.call_on_close(lock.close)


def state_dir():
    load_environment()
    return Path(os.getenv("HERD_STATE_DIR", str(ROOT / "experiments")))


async def sync_all_evidence():
    import fcntl

    from herd.integrations.weave import WeaveIntegration
    store = Store(state_dir() / 'herd.sqlite3')
    integration = WeaveIntegration(os.getenv('HERD_WEAVE_PROJECT') or os.getenv('WANDB_PROJECT'), state_dir())
    with (state_dir() / 'evidence.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        for experiment in store.experiments():
            await integration.sync_store(store, experiment['id'])


def evidence_daemon(stop):
    while not stop.is_set():
        try:
            asyncio.run(sync_all_evidence())
        except Exception as exc:  # noqa: BLE001 - optional integration cannot halt local learning
            # Source records and upload errors persist; retry without stopping learning.
            import logging
            logging.getLogger(__name__).warning('Evidence synchronization pending: %s', type(exc).__name__)
        stop.wait(15)


async def run_with_evidence(engine, experiment_id):
    import threading
    stop = threading.Event()
    worker = threading.Thread(target=evidence_daemon, args=(stop,), daemon=True)
    worker.start()
    try:
        return await engine.run(experiment_id)
    finally:
        stop.set()
        await asyncio.to_thread(worker.join, 5)
        await sync_all_evidence()


def make_engine():
    from herd.adapters.runtime import RuntimeEvaluator
    from herd.engine import Engine
    from herd.gateway import BudgetLedger, GatewayConfig, ProviderGateway
    from herd.learner import Learner
    from herd.task_registry import TaskRegistry

    load_environment()
    config = configuration()
    provider = GatewayConfig.from_env()
    inspected = subprocess.run(
        ["docker", "image", "inspect", "herd-runtime:local", "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspected.returncode:
        raise RuntimeError("Build the HERD Docker image first: docker build -t herd-runtime:local .")
    image_id = inspected.stdout.strip()
    from herd.schemas import digest

    config["runtime_hash"] = digest([config["runtime_hash"], image_id])
    ledger = BudgetLedger(state_dir() / "budget.sqlite3", provider.cap_usd)
    gateway = ProviderGateway(provider, ledger)
    registry = TaskRegistry(config["runtime_hash"], config["docs_hash"])
    runtime = RuntimeEvaluator(registry, mode="docker", image=image_id)
    learner = Learner(
        gateway, runtime, state_dir() / "workspaces", docs=(ROOT / "docs/snapshots/marimo.md").read_text()
    )
    max_workers = int(os.getenv('HERD_MAX_WORKERS', '4'))
    if not 1 <= max_workers <= 10:
        raise ValueError('HERD_MAX_WORKERS must be between 1 and 10')
    engine = Engine(Store(state_dir() / "herd.sqlite3"), registry, learner, state_dir(), provider.config_hash,
                    concurrency=max_workers)
    engine.config.update(
        runtime_hash=config["runtime_hash"], runtime_image_id=image_id, provider=provider.public_dict(),
        max_workers=max_workers
    )
    if os.getenv("WANDB_API_KEY") and os.getenv("WANDB_PROJECT"):
        from herd.integrations.weave import WeaveIntegration

        WeaveIntegration(os.getenv("WANDB_PROJECT"), state_dir()).connect()
    return engine


@app.command()
def preflight():
    """Print configuration readiness without exposing credentials or making paid calls."""
    load_environment()
    cfg = configuration()
    from herd.adapters.runtime import RuntimeEvaluator
    from herd.task_registry import TaskRegistry
    runtime = RuntimeEvaluator(TaskRegistry(cfg["runtime_hash"], cfg["docs_hash"]),
                               image=os.getenv("HERD_RUNTIME_IMAGE", "herd-runtime:local"))
    readiness = asyncio.run(runtime.preflight(browser=True))
    checks = {
        "runtime_hash": cfg["runtime_hash"],
        "docs_hash": cfg["docs_hash"],
        "docker_ready": readiness.get("docker_ready", False),
        "runtime_ready": readiness["ready"],
        "runtime_readiness": readiness,
        "browser_ready": readiness.get("browser", {}).get("ready", False),
        "provider_key_configured": bool(os.getenv("WANDB_API_KEY") or os.getenv("HERD_INFERENCE_API_KEY")),
        "weave_project_configured": bool(os.getenv("WANDB_PROJECT") or os.getenv("HERD_WEAVE_PROJECT")),
        "protocol": cfg["protocol"]["schema_version"],
        "max_workers": int(os.getenv('HERD_MAX_WORKERS', '4')),
        "sponsor_capabilities": provider_capabilities(),
    }
    typer.echo(json.dumps(checks, indent=2))


@app.command()
def health():
    """Verify durable store and event-chain health without model calls."""
    store = Store(state_dir() / 'herd.sqlite3')
    typer.echo(json.dumps({**store.health(), 'event_chains': {
        e['id']: store.verify_events(e['id']) for e in store.experiments()}}, indent=2))


@app.command()
def control(experiment_id: str, action: str):
    """Request pause, cancel, or resume at a durable worker checkpoint."""
    if action not in {'pause', 'cancel', 'resume'}:
        raise typer.BadParameter('Action must be pause, cancel, or resume')
    store = Store(state_dir() / 'herd.sqlite3')
    typer.echo(json.dumps(store.request_control(experiment_id, action), indent=2))


@app.command()
def accounting(experiment_id: str, output: Path | None = None):
    """Export all-stage cost, unresolved reservations and elapsed time."""
    from herd.gateway import BudgetLedger, GatewayConfig
    from herd.reports import experiment_accounting
    load_environment()
    store = Store(state_dir() / 'herd.sqlite3')
    ledger = BudgetLedger(state_dir() / 'budget.sqlite3', GatewayConfig.from_env().cap_usd)
    report = experiment_accounting(store, experiment_id, ledger)
    encoded = json.dumps(report, indent=2)
    if output:
        output.write_text(encoded)
    typer.echo(encoded)


@app.command()
def reconcile(request_id: str, actual_usd: float, evidence: str, operator: str, authorize_retry: bool = False):
    """Settle a provider receipt and optionally authorize a new billed retry generation."""
    from herd.gateway import BudgetLedger, GatewayConfig
    load_environment()
    ledger = BudgetLedger(state_dir() / 'budget.sqlite3', GatewayConfig.from_env().cap_usd)
    ledger.reconcile(request_id, actual_usd, evidence, operator, authorize_retry=authorize_retry)
    typer.echo(json.dumps(ledger.summary(), indent=2))


@app.command()
def backup(destination: Path):
    """Snapshot stopped/paused state and workspaces into a new directory."""
    from herd.backup import backup_state
    typer.echo(json.dumps(backup_state(state_dir(), destination), indent=2))


@app.command()
def restore(source: Path, destination: Path):
    """Verify and restore an offline backup into a new state directory."""
    from herd.backup import restore_state
    typer.echo(json.dumps(restore_state(source, destination), indent=2))


@app.command()
def provider_check():
    """Make one budgeted model request to verify a configured provider contract."""
    from uuid import uuid4

    from herd.gateway import BudgetLedger, GatewayConfig, ProviderGateway
    load_environment()
    config = GatewayConfig.from_env()
    gateway = ProviderGateway(config, BudgetLedger(state_dir() / 'budget.sqlite3', config.cap_usd))
    result = asyncio.run(gateway.complete([{'role': 'user', 'content': 'Reply with the single word READY.'}],
                                         32, 'provider-check-' + uuid4().hex))
    typer.echo(json.dumps({'status': 'verified', 'model': config.model,
                          'input_tokens': result.input_tokens, 'output_tokens': result.output_tokens,
                          'cost_usd': result.cost_usd}, indent=2))


@app.command()
def lifecycle(experiment_id: str, action: str, reason: str, lesson_ids: str = '',
              target_pool_hash: str = '', replacement_id: str = ''):
    """Queue a reviewed retraction, rollback or supersession for a measured boundary check."""
    from herd.lifecycle import request_change
    store = Store(state_dir() / 'herd.sqlite3')
    result = request_change(store, experiment_id, action, reason,
                            lesson_ids=[value for value in lesson_ids.split(',') if value] or None,
                            target_pool_hash=target_pool_hash or None, replacement_id=replacement_id or None)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def false_controls(experiment_id: str):
    """Run registered plausible false lessons through real paired admission diagnostics."""
    engine = make_engine()
    with engine.store.execution_lock():
        asyncio.run(engine.run_false_controls(experiment_id))
    typer.echo(json.dumps(engine.store.list(experiment_id, 'poisoning_control'), indent=2))


@app.command()
def calibrate(experiment_id: str, seed: int = 20260913, tasks: int = 12):
    """Measure the worker on calibration tasks, excluded from lessons and final estimates."""
    from herd.schemas import Partition
    if not 1 <= tasks <= 60:
        raise typer.BadParameter('Calibration task count must be between 1 and 60')
    engine = make_engine()
    if engine.store.get(experiment_id, 'experiment', experiment_id) is None:
        raise typer.BadParameter('Unknown experiment')

    async def measure():
        results = []
        with engine.store.execution_lock():
            for index in range(tasks):
                task = engine.task(experiment_id, Partition.CALIBRATION, seed + index)
                result = await engine.attempt(experiment_id, task, f'calibration-{index}', 0,
                                              engine.pool(experiment_id), arm='calibration', memory='')
                results.append({'run_id': result.run_id, 'task_id': task.task_id,
                                'success': result.result.success if result.result else None,
                                'first_submission_success': result.first_submission_success,
                                'submissions': result.submissions, 'status': result.status})
        record = {'seed': seed, 'results': results, 'mode': 'measured',
                  'note': 'Calibration is excluded from lesson creation and final estimates.'}
        engine.store.put(experiment_id, 'calibration', str(seed), record)
        return record

    typer.echo(json.dumps(asyncio.run(measure()), indent=2))


@app.command()
def init():
    """Freeze configuration and baselines for a new experiment."""
    engine = make_engine()
    typer.echo(engine.create()["id"])


@app.command()
def run(experiment_id: str):
    """Run or resume the full protocol, bounded by configured dollar cap."""
    engine = make_engine()
    asyncio.run(run_with_evidence(engine, experiment_id))


@app.command()
def serve(port: int = 8000, demo: bool = False):
    """Serve the local control API; demo mode disables mutations."""
    import uvicorn

    from herd.api import create_app

    load_environment()
    engine = None
    if not demo:
        try:
            engine = make_engine()
        except (ValueError, RuntimeError):
            pass
    import threading
    stop = threading.Event()
    worker = threading.Thread(target=evidence_daemon, args=(stop,), daemon=True)
    worker.start()
    try:
        uvicorn.run(create_app(Store(state_dir() / "herd.sqlite3"), engine, demo), host="127.0.0.1", port=port)
    finally:
        stop.set()
        worker.join(timeout=5)


@app.command()
def control_room(port: int = 2718):
    """Open the reactive marimo experiment dashboard."""
    subprocess.run(["marimo", "run", str(ROOT / "app/control_room.py"), "--port", str(port)], check=True)


@app.command()
def validate_fixtures(browser: bool = False):
    """Exercise real marimo references and negative fixtures; no model improvement claims."""
    from herd.adapters.runtime import RuntimeEvaluator
    from herd.schemas import Partition
    from herd.task_registry import TaskRegistry

    cfg = configuration()
    registry = TaskRegistry(cfg["runtime_hash"], cfg["docs_hash"])
    runtime = RuntimeEvaluator(registry, mode="trusted-reference")

    async def validate():
        failures = []
        for n in range(12):
            task = registry.generate(Partition.CALIBRATION, n)
            positive = await runtime.evaluate(
                task,
                registry.reference_source(task),
                state_dir() / "validation" / f"{n}-reference",
                browser=browser,
            )
            negative = await runtime.evaluate(
                task, registry.negative_source(task), state_dir() / "validation" / f"{n}-negative"
            )
            typer.echo(f"{task.family_id}: reference={positive.success} negative={negative.success}")
            if not positive.success or negative.success:
                failures.append(task.task_id)
        if failures:
            raise RuntimeError(f"Fixture validation failed: {failures}")

    asyncio.run(validate())


@app.command()
def sync_weave(experiment_id: str):
    """Recover and upload genuine local evidence, native evaluations and links."""
    from herd.integrations.weave import WeaveIntegration
    load_environment()
    store = Store(state_dir() / "herd.sqlite3")
    if not store.get(experiment_id, "experiment", experiment_id):
        raise typer.BadParameter("Unknown experiment")
    integration = WeaveIntegration(os.getenv("HERD_WEAVE_PROJECT") or os.getenv("WANDB_PROJECT"), state_dir())
    typer.echo(json.dumps(asyncio.run(integration.sync_store(store, experiment_id)), indent=2))


@app.command()
def aria_export(experiment_id: str):
    """Export development-only evidence for the authentic ARIA interface."""
    from herd.integrations.aria import export_bundle

    store = Store(state_dir() / "herd.sqlite3")
    tasks = {t["task_id"] for t in store.list(experiment_id, "task") if t["partition"] == "development"}
    attempts = [a for a in store.list(experiment_id, "attempt") if a["task_id"] in tasks]
    path = export_bundle(
        experiment_id, {"partition": "development", "attempts": attempts}, state_dir() / "aria"
    )
    typer.echo(str(path))


@app.command()
def aria_import(bundle: Path, report: Path, source_url: str, operator: str, curriculum_action: str,
                track_weights: str = ""):
    """Attach an operator-attested real ARIA report, URL, and curriculum decision."""
    from herd.integrations.aria import import_analysis

    record = import_analysis(bundle, report.read_text(), source_url, operator, curriculum_action)
    store = Store(state_dir() / "herd.sqlite3")
    store.put(record["experiment_id"], "aria_analysis", record["report_hash"], record)
    store.event(record["experiment_id"], "aria_analysis_attached", record)
    if track_weights:
        from herd.curriculum import queue_curriculum
        queue_curriculum(store, record["experiment_id"], record["report_hash"],
                         json.loads(track_weights), curriculum_action)
    typer.echo("ARIA report attached with provenance")


@app.command()
def demo_probe(experiment_id: str, seed: int = 424242):
    """Run a predetermined fresh-worker demonstration pair from a frozen pool."""
    from herd.schemas import Partition

    engine = make_engine()
    if not engine.store.get(experiment_id, "final_freeze", "current"):
        raise typer.BadParameter("Freeze the learned pool through final evaluation before recording a demo")
    task = engine.task(experiment_id, Partition.DEMONSTRATION, seed)
    pool = engine.pool(experiment_id)

    async def probe():
        from herd.engine import safe_gather

        results = await safe_gather(
            engine.attempt(experiment_id, task, "demo-0", 5, pool, "no_pool", memory=""),
            engine.attempt(experiment_id, task, "demo-0", 5, pool, "admitted_pool"),
        )
        for result in results:
            if result.source:
                evidence = await engine.learner.evaluator.evaluate(
                    task, result.source, Path(result.workspace) / "browser", browser=True
                )
                engine.store.put(experiment_id, "demo_browser", result.run_id, evidence)
        typer.echo(task.task_id)

    with engine.store.execution_lock():
        asyncio.run(probe())


if __name__ == "__main__":
    app()

from pathlib import Path

import pytest

from herd.adapters.runtime import RuntimeEvaluator
from herd.schemas import Partition
from herd.task_registry import TaskRegistry


@pytest.mark.asyncio
async def test_local_refuses_untrusted_source(tmp_path):
    registry = TaskRegistry("runtime", "docs")
    task = registry.generate(Partition.CALIBRATION, 0)
    evaluator = RuntimeEvaluator(registry, mode="trusted-reference")
    result = await evaluator.evaluate(task, "raise RuntimeError('untrusted')", tmp_path)
    assert not result.success
    assert "rejects arbitrary code" in result.infrastructure_error


def test_docker_security_boundary():
    evaluator = RuntimeEvaluator(TaskRegistry("runtime", "docs"))
    args = evaluator.docker_args(Path("/tmp/one-submission"), "test")
    assert "--network=none" in args
    assert "--read-only" in args
    assert "--cap-drop=ALL" in args
    assert "--user=65534:65534" in args
    assert sum(1 for arg in args if arg == "--mount") == 1
    assert not any("oracle" in arg or "WANDB" in arg for arg in args)


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", range(12))
async def test_real_marimo_reference_and_negative_fixture(seed, tmp_path):
    """Real runtime checks of authored controls; not measured model-learning gains."""
    registry = TaskRegistry("runtime", "docs")
    task = registry.generate(Partition.CALIBRATION, seed)
    evaluator = RuntimeEvaluator(registry, mode="trusted-reference")
    reference = await evaluator.evaluate(task, registry.reference_source(task), tmp_path / "positive")
    assert reference.success, reference.model_dump()
    assert all(
        any(c.name.startswith(name) and c.passed for c in reference.checks)
        for name in ("structure", "startup", "integrity")
    )
    negative = await evaluator.evaluate(task, registry.negative_source(task), tmp_path / "negative")
    assert not negative.success
    assert negative.infrastructure_error is None
    assert reference.mode == "trusted_reference_fixture"


@pytest.mark.asyncio
async def test_docker_references_and_containment():
    import json
    import os
    import uuid

    if os.environ.get("HERD_SKIP_RUNTIME") == "1":
        pytest.skip("HERD_SKIP_RUNTIME=1 disables Docker containment checks")
    registry = TaskRegistry("runtime", "docs")
    evaluator = RuntimeEvaluator(registry)
    workspace = Path.cwd() / ".herd" / ("docker-test-" + uuid.uuid4().hex)
    workspace.mkdir(parents=True)
    for seed in range(12):
        task = registry.generate(Partition.FINAL, 100000 + seed)
        reference = await evaluator.evaluate(task, registry.reference_source(task), workspace)
        assert reference.success, reference.model_dump()
        negative = await evaluator.evaluate(task, registry.negative_source(task), workspace)
        assert not negative.success and negative.infrastructure_error is None
    # A valid alternate implementation must pass; acceptance is behavioral, not exact-source matching.
    task = registry.generate(Partition.CALIBRATION, 0)
    alternative = (
        registry.reference_source(task)
        .replace(
            "return sum(r['amount'] for r in rows) * value",
            "total = 0\n        for row in rows:\n            total += row['amount']\n        return total * value",
        )
        .replace("def calculation():", "def alternate_calculation():")
    )
    alternate = await evaluator.evaluate(task, alternative, workspace)
    assert alternate.success, alternate.model_dump()
    fake_widget = registry.reference_source(task).replace(
        "control = mo.ui.slider(start=-5, stop=15, step=1, value=1, label='Threshold')",
        "from types import SimpleNamespace as _Namespace\n    control = _Namespace(value=1)",
    )
    fake = await evaluator.evaluate(task, fake_widget, workspace)
    assert not fake.success and fake.infrastructure_error is None
    state_task = registry.generate(Partition.CALIBRATION, 9)
    bypass_state = (
        registry.reference_source(state_task)
        .replace(
            "def transform(compute, records, get_value):",
            "def transform(compute, records, get_value, control):",
        )
        .replace("compute(records, get_value())", "compute(records, control.value)")
    )
    bypass = await evaluator.evaluate(state_task, bypass_state, workspace)
    assert not bypass.success and any(
        c.name.startswith("direct_state") and not c.passed for c in bypass.checks
    )
    task = registry.generate(Partition.CALIBRATION, 0)
    containment = """import os, socket
assert os.getuid() == 65534
assert not any(k.endswith('API_KEY') for k in os.environ)
try:
    open('/etc/herd-write-probe', 'w').write('bad')
    raise AssertionError('root filesystem was writable')
except (PermissionError, OSError):
    pass
try:
    socket.create_connection(('1.1.1.1',443),timeout=1)
    raise AssertionError('unexpected network egress')
except OSError:
    pass
"""
    probe = await evaluator.evaluate(task, containment + registry.reference_source(task), workspace)
    assert probe.success, probe.model_dump()
    (workspace / "containment-result.json").write_text(json.dumps(probe.model_dump(mode="json"), indent=2))


@pytest.mark.asyncio
async def test_real_browser_slider_and_form():
    import os
    import uuid

    if os.environ.get("HERD_SKIP_RUNTIME") == "1":
        pytest.skip("HERD_SKIP_RUNTIME=1 disables browser integration checks")
    registry = TaskRegistry("runtime", "docs")
    evaluator = RuntimeEvaluator(registry)
    workspace = Path.cwd() / ".herd" / ("browser-test-" + uuid.uuid4().hex)
    for seed in range(12):
        task = registry.generate(Partition.CALIBRATION, seed)
        result = await evaluator.evaluate(task, registry.reference_source(task), workspace, browser=True)
        assert result.success, result.model_dump()
        assert any(check.name == "browser_interaction" and check.passed for check in result.checks)
        if task.track == 3:
            assert any(check.name == "form_waits_for_submit" and check.passed for check in result.checks)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["create", "proxy", "attach"])
async def test_browser_cancellation_reaps_every_management_child(stage, tmp_path, monkeypatch):
    import asyncio
    import sys

    from herd.adapters.browser_oracle import BrowserOracle

    real_spawn = asyncio.create_subprocess_exec
    processes, calls = [], []
    reached = asyncio.Event()

    async def fake_spawn(*args, **kwargs):
        calls.append(args)
        is_create = args[:3] == ("docker", "network", "create")
        is_attach = args[:3] == ("docker", "network", "connect")
        is_proxy = args[:3] == ("docker", "run", "-d")
        is_server = args[:2] == ("docker", "run") and not is_proxy
        target = {"create": is_create, "proxy": is_proxy, "attach": is_attach}[stage]
        code = "import time; time.sleep(300)" if target or is_server else "pass"
        child = await real_spawn(sys.executable, "-c", code, **kwargs)
        processes.append(child)
        if target:
            reached.set()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    registry = TaskRegistry("runtime", "docs")
    task = registry.generate(Partition.CALIBRATION, 3)
    notebook = tmp_path / "notebook.py"
    notebook.write_text(registry.reference_source(task))
    operation = asyncio.create_task(BrowserOracle(RuntimeEvaluator(registry)).evaluate(task, notebook))
    await asyncio.wait_for(reached.wait(), 5)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(operation, 10)
    assert all(child.returncode is not None for child in processes)
    assert sum(args[:3] == ("docker", "rm", "-f") for args in calls) == 2
    assert any(args[:3] == ("docker", "network", "rm") for args in calls)


@pytest.mark.asyncio
async def test_browser_management_timeout_reaps_child(monkeypatch):
    import asyncio
    import sys

    from herd.adapters.browser_oracle import _management

    real_spawn = asyncio.create_subprocess_exec
    children = []

    async def fake_spawn(*args, **kwargs):
        child = await real_spawn(sys.executable, "-c", "import time; time.sleep(300)", **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    with pytest.raises(TimeoutError):
        await _management("docker", "network", "create", "test", timeout=0.05)
    assert children[0].returncode is not None


@pytest.mark.asyncio
async def test_browser_repeated_cancellation_drains_cleanup(tmp_path, monkeypatch):
    import asyncio
    import sys

    from herd.adapters.browser_oracle import BrowserOracle

    real_spawn = asyncio.create_subprocess_exec
    children = []
    startup = asyncio.Event()
    cleaning = asyncio.Event()

    async def fake_spawn(*args, **kwargs):
        creating = args[:3] == ("docker", "network", "create")
        code = "import time; time.sleep(300)" if creating else "import time; time.sleep(.1)"
        child = await real_spawn(sys.executable, "-c", code, **kwargs)
        children.append(child)
        (startup if creating else cleaning).set()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    registry = TaskRegistry("runtime", "docs")
    task = registry.generate(Partition.CALIBRATION, 3)
    notebook = tmp_path / "notebook.py"
    notebook.write_text(registry.reference_source(task))
    operation = asyncio.create_task(BrowserOracle(RuntimeEvaluator(registry)).evaluate(task, notebook))
    await asyncio.wait_for(startup.wait(), 5)
    operation.cancel()
    await asyncio.wait_for(cleaning.wait(), 5)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(operation, 5)
    assert len(children) == 4
    assert all(child.returncode is not None for child in children)


@pytest.mark.asyncio
async def test_preflight_requires_actual_browser_readiness(monkeypatch):
    import herd.adapters.runtime as runtime_module

    async def management(*command):
        if command[1] == "info":
            return 0, b"27.0", b""
        return 0, b'[{"Id":"sha256:test"}]', b""

    async def browser_unavailable():
        return {"ready": False, "reason": "Chromium missing dependency"}

    monkeypatch.setattr(runtime_module, "_management", management)
    monkeypatch.setattr(runtime_module.shutil, "which", lambda cmd: "/usr/bin/docker")
    runtime = RuntimeEvaluator(TaskRegistry("runtime", "docs"))
    monkeypatch.setattr(runtime, "_browser_readiness", browser_unavailable)
    result = await runtime.preflight(browser=True)
    assert not result["ready"] and result["docker_ready"] and result["image_ready"]
    assert result["reason"] == "Chromium missing dependency"


@pytest.mark.asyncio
async def test_browser_preflight_cancellation_acquires_and_closes_launched_child(monkeypatch):
    import asyncio

    import playwright.async_api

    started, release = asyncio.Event(), asyncio.Event()
    state = []

    class Browser:
        version = "fixture"

        async def close(self):
            state.append("browser_closed")

    class Chromium:
        async def launch(self, **kwargs):
            started.set()
            await release.wait()
            return Browser()

    class Driver:
        chromium = Chromium()

        async def stop(self):
            state.append("driver_stopped")

    class Manager:
        async def start(self):
            return Driver()

    monkeypatch.setattr(playwright.async_api, "async_playwright", Manager)
    runtime = RuntimeEvaluator(TaskRegistry("runtime", "docs"))
    operation = asyncio.create_task(runtime._browser_readiness())
    await started.wait()
    operation.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert state == ["browser_closed", "driver_stopped"]


def test_browser_duplicate_task_elements_are_candidate_failure_not_infrastructure():
    from playwright.async_api import Error

    from herd.adapters.browser_oracle import classify_browser_error

    result = classify_browser_error(Error("Locator resolved to two elements: strict mode violation"))
    assert result.name == "browser_behavior" and not result.passed
    with pytest.raises(OSError, match="Browser infrastructure failed"):
        classify_browser_error(Error("Target page, context or browser has been closed"))


@pytest.mark.asyncio
async def test_notebook_cannot_author_the_verdict(tmp_path):
    """A submission that fakes the runner protocol must not score as a pass.

    Two vectors, both previously successful: writing a forged result straight to fd 1
    and exiting before the runner speaks, and doing the same from inside an otherwise
    valid notebook. Expected values are derivable from the public task id, so secrecy
    of the oracle is not what makes this fail.
    """
    import os as _os

    if _os.getenv("HERD_SKIP_RUNTIME"):
        pytest.skip("Runtime checks disabled")
    from herd.config import configuration
    from herd.schemas import Partition
    from herd.task_registry import TaskRegistry

    config = configuration()
    registry = TaskRegistry(config["runtime_hash"], config["docs_hash"])
    evaluator = RuntimeEvaluator(registry, mode="docker")
    if not (await evaluator.preflight()).get("ready"):
        pytest.skip("Docker runtime unavailable")

    task = registry.generate(Partition.CALIBRATION, 3)
    probes = registry.private_probes(task)
    payload = {
        "initial": registry.expected_result(task),
        "observed": [
            {
                "function": registry.expected(task, p["records"], p["value"]),
                "reactive_result": registry.expected_result(task, p),
                "result_defined": True,
            }
            for p in probes
        ],
        "actual_ui_objects": True,
    }
    hijack = f"import os, json\nos.write(1, json.dumps({payload!r}).encode())\nos._exit(0)\n"

    bare = await evaluator.evaluate(task, hijack, tmp_path / "bare", browser=False)
    assert not bare.success
    assert not any(c.passed for c in bare.checks if c.name.startswith("harness_"))

    inside = await evaluator.evaluate(
        task, hijack + registry.reference_source(task), tmp_path / "inside", browser=False
    )
    assert not inside.success

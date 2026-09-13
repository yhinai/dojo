"""Real browser reactivity checks, only against an isolated app origin.

Docker apps use a throwaway internal network and loopback-published port. The
browser rejects all requests except the app origin; it receives no credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import uuid
from pathlib import Path

from herd.schemas import CheckResult, TaskManifest


async def _drain(awaitable):
    """Finish a bounded cleanup despite repeated cancellation of its owner."""
    operation = asyncio.ensure_future(awaitable)
    while not operation.done():
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            continue
    return operation.result()


async def _reap(process):
    if process is not None and process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await asyncio.wait_for(process.wait(), 5)


async def _spawn(*command, **kwargs):
    """A cancellation racing subprocess creation must still acquire and reap the child."""
    creation = asyncio.create_task(asyncio.create_subprocess_exec(*command, **kwargs))
    try:
        return await asyncio.shield(creation)
    except asyncio.CancelledError:
        process = await _drain(creation)
        await _drain(_reap(process))
        raise


async def _management(*command, timeout=10):
    process = None
    try:
        process = await _spawn(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, error = await asyncio.wait_for(process.communicate(), timeout)
        return process.returncode, output, error
    finally:
        await _drain(_reap(process))


async def _cleanup(process, commands):
    await _reap(process)
    for command in commands:
        try:
            await _management(*command)
        except (OSError, TimeoutError):
            # A stopped Docker daemon cannot clean resources now; commands are finite,
            # and no management child is abandoned. The next preflight reports it.
            continue


def classify_browser_error(error: Exception) -> CheckResult:
    """Ambiguous task elements are candidate defects; engine/connection faults are infrastructure."""
    detail = str(error)[:1000]
    if "strict mode violation" in str(error).lower():
        return CheckResult(name="browser_behavior", passed=False, detail=detail)
    raise OSError("Browser infrastructure failed: " + detail) from error


class BrowserOracle:
    def __init__(self, runtime):
        self.runtime = runtime

    async def evaluate(self, task: TaskManifest, notebook: Path) -> list[CheckResult]:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright, expect

        checks = []
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        name = "herd-web-" + uuid.uuid4().hex[:12]
        network = name + "-network"
        proxy_name = name + "-ingress"
        log_file = notebook.parent.parent / f"{name}.log"
        process = None
        try:
            if self.runtime.mode == "docker":
                code, _, error = await _management(
                    "docker",
                    "network",
                    "create",
                    "--internal",
                    network,
                )
                if code:
                    raise OSError("Cannot create isolated browser network: " + error.decode()[-1000:])
                command = self.runtime.docker_args(notebook.parent, name)
                command[command.index("--network=none")] = "--network=" + network
                position = command.index("-i")
                command[position : position + 1] = []
                image_index = command.index(self.runtime.image)
                command[image_index + 1 :] = [
                    "marimo",
                    "run",
                    "/submission/notebook.py",
                    "--host=0.0.0.0",
                    "--port=8080",
                    "--headless",
                    "--no-token",
                ]
            else:
                command = [
                    sys.executable,
                    "-m",
                    "marimo",
                    "run",
                    str(notebook.resolve()),
                    "--host=127.0.0.1",
                    f"--port={port}",
                    "--headless",
                    "--no-token",
                ]
            with log_file.open("wb") as log:
                process = await _spawn(
                    *command,
                    stdout=log,
                    stderr=log,
                    env={
                        "PATH": os.environ.get("PATH", ""),
                        "HOME": os.path.expanduser("~")
                        if self.runtime.mode == "docker"
                        else str(notebook.parent.resolve()),
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                )
                if self.runtime.mode == "docker":
                    proxy_code = """import socket,select,threading,sys
TARGET=sys.argv[1]
def forward(client):
    try:
        upstream=socket.create_connection((TARGET,8080),timeout=10)
        with client,upstream:
            while True:
                readable,_,_=select.select([client,upstream],[],[],30)
                if not readable: break
                for source in readable:
                    data=source.recv(65536)
                    if not data:return
                    (upstream if source is client else client).sendall(data)
    except OSError:client.close()
server=socket.socket();server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
server.bind(('0.0.0.0',8080));server.listen(32)
while True:
    client,_=server.accept()
    threading.Thread(target=forward,args=(client,),daemon=True).start()
"""
                    code, _, error = await _management(
                        "docker",
                        "run",
                        "-d",
                        "--name",
                        proxy_name,
                        "--network=bridge",
                        "--read-only",
                        "--cap-drop=ALL",
                        "--security-opt=no-new-privileges",
                        "--memory=128m",
                        "--pids-limit=64",
                        "--user=65534:65534",
                        "-p",
                        f"127.0.0.1:{port}:8080",
                        self.runtime.image,
                        "python",
                        "-c",
                        proxy_code,
                        name,
                    )
                    if code:
                        raise OSError("Cannot start trusted ingress proxy: " + error.decode()[-1000:])
                    code, _, error = await _management(
                        "docker",
                        "network",
                        "connect",
                        network,
                        proxy_name,
                    )
                    if code:
                        raise OSError("Cannot attach trusted ingress proxy: " + error.decode()[-1000:])
                origin = f"http://127.0.0.1:{port}"
                import httpx

                async with httpx.AsyncClient() as client:
                    for _ in range(100):
                        if process.returncode is not None:
                            raise OSError("marimo server exited: " + log_file.read_text()[-2000:])
                        try:
                            response = await client.get(origin, timeout=1)
                            if response.status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(0.1)
                    else:
                        raise OSError("marimo server did not start within 10 seconds")
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(headless=True)
                    try:
                        context = await browser.new_context(service_workers="block", accept_downloads=False)

                        async def websocket_route(route):
                            if route.url.startswith(f"ws://127.0.0.1:{port}/"):
                                route.connect_to_server()
                            else:
                                await route.close()

                        await context.route_web_socket("**/*", websocket_route)
                        await context.route(
                            "**/*",
                            lambda route: (
                                route.continue_()
                                if route.request.url.startswith(origin + "/")
                                else route.abort()
                            ),
                        )
                        page = await context.new_page()
                        await page.goto(origin)
                        result = page.locator("#herd-result")
                        initial = self.runtime.registry.expected_result(task)
                        await expect(result).to_have_text(json.dumps(initial, sort_keys=True), timeout=20000)
                        checks.append(CheckResult(name="browser_initial", passed=True))
                        slider = page.get_by_role("slider").first
                        await slider.focus()
                        await slider.press("ArrowRight")
                        if task.track == 3:
                            # UI event settles, but result must remain committed to the old value.
                            await page.wait_for_timeout(300)
                            await expect(result).to_have_text(json.dumps(initial, sort_keys=True))
                            checks.append(CheckResult(name="form_waits_for_submit", passed=True))
                            await page.get_by_role("button", name="Apply", exact=True).click()
                        kind = task.public_fixture["interaction_contract"]
                        probe = {
                            "records": task.public_fixture["records"],
                            "value": 2,
                            "selection": [0],
                            "include_negative": True,
                            "offset": 0,
                            "enabled": True,
                        }
                        expected = self.runtime.registry.expected_result(task, probe)
                        await expect(result).to_have_text(json.dumps(expected, sort_keys=True), timeout=10000)
                        checks.append(CheckResult(name="browser_interaction", passed=True))
                        if kind == "table":
                            # Header select-all plus one checkbox per fixture row.
                            await page.get_by_role("checkbox").nth(2).click()
                            probe["selection"] = [0, 1]
                        elif kind == "multi_offset":
                            await page.get_by_role("slider").nth(1).focus()
                            await page.get_by_role("slider").nth(1).press("ArrowRight")
                            probe["offset"] = 1
                        elif kind == "multi_checkbox":
                            await slider.focus()
                            await slider.press("Home")
                            probe["value"] = -5
                            await page.get_by_role("checkbox", name="Include negatives").click()
                            probe["include_negative"] = False
                        elif kind == "stop":
                            await page.get_by_role("checkbox", name="Enabled").click()
                            await expect(result).to_have_count(0, timeout=10000)
                            await expect(page.get_by_text("Paused", exact=True)).to_be_visible()
                            checks.append(CheckResult(name="browser_stops_downstream", passed=True))
                            await page.get_by_role("checkbox", name="Enabled").click()
                        if kind in ("table", "multi_offset", "multi_checkbox", "stop"):
                            expected = self.runtime.registry.expected_result(task, probe)
                            await expect(result).to_have_text(
                                json.dumps(expected, sort_keys=True), timeout=10000
                            )
                            checks.append(CheckResult(name="browser_secondary_dependency", passed=True))
                        screenshot = notebook.parent.parent / f"{name}.png"
                        await page.screenshot(path=str(screenshot), full_page=True)
                        checks[-1].evidence = {"screenshot": str(screenshot), "server_log": str(log_file)}
                    finally:
                        await _drain(asyncio.wait_for(browser.close(), 10))
        except (AssertionError, PlaywrightTimeoutError) as exc:
            checks.append(CheckResult(name="browser_behavior", passed=False, detail=str(exc)[:1000]))
        except PlaywrightError as exc:
            checks.append(classify_browser_error(exc))
        finally:
            commands = (
                [
                    ["docker", "rm", "-f", proxy_name],
                    ["docker", "rm", "-f", name],
                    ["docker", "network", "rm", network],
                ]
                if self.runtime.mode == "docker"
                else []
            )
            cleanup = asyncio.create_task(_cleanup(process, commands))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await _drain(cleanup)
                raise
        return checks

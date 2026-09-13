from __future__ import annotations

import ast
import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from herd.adapters.browser_oracle import _cleanup, _drain, _management, _spawn
from herd.integrations.weave import traced
from herd.schemas import BehaviorResult, CheckResult, TaskManifest, digest
from herd.task_registry import TaskRegistry


class RuntimeEvaluator:
    def __init__(
        self,
        registry: TaskRegistry,
        mode: str = "docker",
        image: str = "herd-runtime:local",
        timeout_seconds: float = 45,
    ):
        if mode not in ("docker", "trusted-reference"):
            raise ValueError("runtime mode must be docker or trusted-reference")
        self.registry, self.mode, self.image, self.timeout_seconds = registry, mode, image, timeout_seconds

    async def _browser_readiness(self):
        """Actually launch Chromium, acquiring and closing children even during cancellation."""
        cached = getattr(self, "_browser_ready_cache", None)
        if cached and time.monotonic() - cached[0] < 20:
            return {**cached[1], "cached": True}
        playwright = None
        browser = None
        operation = None
        try:
            from playwright.async_api import async_playwright

            operation = asyncio.create_task(async_playwright().start())
            try:
                playwright = await asyncio.shield(operation)
            except asyncio.CancelledError:
                playwright = await _drain(operation)
                raise
            operation = asyncio.create_task(playwright.chromium.launch(headless=True, timeout=10000))
            try:
                browser = await asyncio.shield(operation)
            except asyncio.CancelledError:
                try:
                    browser = await _drain(operation)
                finally:
                    raise
            result = {"ready": True, "engine": "chromium", "version": browser.version, "cached": False}
        except Exception as exc:  # noqa: BLE001 - readiness failures must prevent all paid calls
            return {
                "ready": False,
                "reason": f"Chromium launch unavailable: {type(exc).__name__}: {str(exc)[-1500:]}",
            }
        finally:

            async def close_children():
                try:
                    if browser:
                        await asyncio.wait_for(browser.close(), 5)
                finally:
                    if playwright:
                        await asyncio.wait_for(playwright.stop(), 5)

            await _drain(close_children())
        self._browser_ready_cache = (time.monotonic(), result)
        return result

    async def preflight(self, browser: bool = False) -> dict:
        if self.mode == "trusted-reference":
            result = {
                "ready": True,
                "mode": self.mode,
                "secure_for_generated_code": False,
                "limitation": "Only exact registry reference and negative-control sources are permitted.",
            }
        else:
            if not shutil.which("docker"):
                return {"ready": False, "reason": "Docker executable not found", "docker_ready": False}
            try:
                code, stdout, stderr = await _management("docker", "info", "--format", "{{.ServerVersion}}")
                if code:
                    return {"ready": False, "reason": stderr.decode()[-2000:], "docker_ready": False}
                code, stdout, stderr = await _management("docker", "image", "inspect", self.image)
                if code:
                    return {
                        "ready": False,
                        "reason": stderr.decode()[-2000:],
                        "docker_ready": True,
                        "image_ready": False,
                    }
                details = json.loads(stdout)[0]
                result = {
                    "ready": True,
                    "image_id": details["Id"],
                    "mode": self.mode,
                    "secure_for_generated_code": True,
                    "docker_ready": True,
                    "image_ready": True,
                }
            except (TimeoutError, OSError, ValueError, IndexError, KeyError) as exc:
                return {"ready": False, "reason": str(exc), "docker_ready": False}
        if browser:
            try:
                result["browser"] = await self._browser_readiness()
            except Exception as exc:  # noqa: BLE001 - readiness failures must prevent all paid calls
                result["browser"] = {"ready": False, "reason": str(exc)}
            if not result["browser"]["ready"]:
                result.update(ready=False, reason=result["browser"]["reason"])
        return result

    def docker_args(self, mount: Path, name: str) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory=512m",
            "--cpus=1",
            "--user=65534:65534",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=96m",
            "-e",
            "HOME=/tmp",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "--mount",
            f"type=bind,src={mount.resolve()},dst=/submission,readonly",
            "-i",
            self.image,
            "python",
            "/opt/herd/runner.py",
            "/submission/notebook.py",
        ]

    async def _communicate(self, process, payload: bytes):
        async def bounded(stream):
            chunks, size = [], 0
            while True:
                chunk = await stream.read(16384)
                if not chunk:
                    return b"".join(chunks)
                size += len(chunk)
                if size > 1_000_000:
                    raise ValueError("Candidate output exceeded 1 MB")
                chunks.append(chunk)

        process.stdin.write(payload)
        await process.stdin.drain()
        process.stdin.close()
        readers = [asyncio.create_task(bounded(process.stdout)), asyncio.create_task(bounded(process.stderr))]
        try:
            stdout, stderr = await asyncio.gather(*readers)
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
        await process.wait()
        return stdout, stderr

    @traced("evaluate_notebook")
    async def evaluate(
        self, task: TaskManifest, source: str, workspace: Path, browser: bool = False
    ) -> BehaviorResult:
        started = time.monotonic()
        mode = "trusted_reference_fixture" if self.mode == "trusted-reference" else "measured"
        result = BehaviorResult(
            task_id=task.task_id, success=False, checks=[], artifact_hash=digest(source), mode=mode
        )
        if self.mode == "trusted-reference" and source not in (
            self.registry.reference_source(task),
            self.registry.negative_source(task),
        ):
            result.infrastructure_error = (
                "Local execution rejects arbitrary code; configure Docker for model submissions."
            )
            result.checks.append(
                CheckResult(name="integrity", passed=False, detail="Source is not on local allowlist")
            )
            return result
        ready = await self.preflight(browser=browser)
        if not ready["ready"]:
            result.infrastructure_error = ready["reason"]
            result.checks.append(
                CheckResult(name="integrity", passed=False, detail="Runtime isolation preflight unavailable")
            )
            return result
        try:
            ast.parse(source)
            result.checks.append(
                CheckResult(
                    name="structure_syntax",
                    passed=True,
                    detail="Python AST parses successfully; execution validates marimo graph.",
                )
            )
        except SyntaxError:
            result.checks.extend(
                [
                    CheckResult(name="structure_syntax", passed=False, detail="Python syntax error"),
                    CheckResult(name="integrity", passed=False, detail="Execution contract not reached"),
                ]
            )
            return result
        # Unique directory mounts exactly one source, never the experiment/pool/oracle tree.
        sandbox = Path(workspace) / ("submission-" + uuid.uuid4().hex)
        sandbox.mkdir(parents=True)
        notebook = sandbox / "notebook.py"
        notebook.write_text(source)
        mount_names = {p.name for p in sandbox.iterdir()}
        name = "herd-" + uuid.uuid4().hex[:16]
        command = (
            self.docker_args(sandbox, name)
            if self.mode == "docker"
            else [sys.executable, str(Path(__file__).with_name("runner.py")), str(notebook.resolve())]
        )
        probes = self.registry.private_probes(task)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.path.expanduser("~") if self.mode == "docker" else str(sandbox.resolve()),
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "en_US.UTF-8",
        }
        process = None
        try:
            process = await _spawn(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    self._communicate(process, json.dumps(probes).encode()), self.timeout_seconds
                )
            except (TimeoutError, ValueError) as exc:
                process.kill()
                await process.wait()
                result.checks.append(
                    CheckResult(
                        name="execution_budget", passed=False, detail=str(exc) or "Notebook timed out"
                    )
                )
                return result
            log = sandbox.parent / (sandbox.name + "-execution.json")
            log.write_text(
                json.dumps(
                    {
                        "returncode": process.returncode,
                        "stdout": stdout.decode(errors="replace")[-30000:],
                        "stderr": stderr.decode(errors="replace")[-30000:],
                    },
                    indent=2,
                )
            )
            result.evidence_paths = [str(notebook), str(log)]
            if process.returncode:
                # Docker daemon failures are infrastructure; nonzero Python is candidate execution failure.
                if self.mode == "docker" and process.returncode in (125, 126, 127):
                    result.infrastructure_error = stderr.decode(errors="replace")[-2000:]
                else:
                    result.checks.append(
                        CheckResult(
                            name="execution", passed=False, detail=stderr.decode(errors="replace")[-2000:]
                        )
                    )
                return result
            try:
                observed = json.loads(stdout)
            except (ValueError, UnicodeDecodeError):
                result.checks.append(
                    CheckResult(name="runner_protocol", passed=False, detail="Invalid runner output")
                )
                return result
            if not isinstance(observed, dict):
                result.checks.append(
                    CheckResult(name="runner_protocol", passed=False, detail="Runner returned a non-object")
                )
                return result
            if "candidate_error" in observed:
                result.checks.append(
                    CheckResult(name="startup", passed=False, detail="Fresh app.run did not complete")
                )
                result.checks.append(
                    CheckResult(name="notebook_execution", passed=False, detail=observed["candidate_error"])
                )
                return result
            result.checks.append(
                CheckResult(
                    name="startup",
                    passed=True,
                    detail="Fresh runner imported the notebook and completed app.run with required outputs",
                )
            )
            expected_initial = self.registry.expected(task, task.public_fixture["records"], 1)
            result.checks.append(
                CheckResult(name="initial_result", passed=observed.get("initial") == expected_initial)
            )
            actual = observed.get("observed", [])
            if not isinstance(actual, list) or not all(isinstance(item, dict) for item in actual):
                result.checks.append(
                    CheckResult(name="runner_protocol", passed=False, detail="Invalid probe result structure")
                )
                return result
            result.checks.append(CheckResult(name="probe_count", passed=len(actual) == len(probes)))
            for index, (probe, output) in enumerate(zip(probes, actual)):
                expected = self.registry.expected(task, probe["records"], probe["value"])
                for field in ("function", "reactive_result"):
                    result.checks.append(
                        CheckResult(
                            name=f"{field}_{index}",
                            passed=output.get(field) == expected,
                            detail="Behavior matches host oracle"
                            if output.get(field) == expected
                            else "Behavior mismatch",
                        )
                    )
            if browser and all(c.passed for c in result.checks):
                from herd.adapters.browser_oracle import BrowserOracle

                browser_checks = await BrowserOracle(self).evaluate(task, notebook)
                result.checks.extend(browser_checks)
                for check in browser_checks:
                    result.evidence_paths.extend(str(path) for path in check.evidence.values())
            result.success = bool(result.checks) and all(c.passed for c in result.checks)
        except (TimeoutError, OSError) as exc:
            result.infrastructure_error = str(exc)
        finally:
            try:
                unchanged = notebook.exists() and digest(notebook.read_text()) == digest(source)
            except (OSError, UnicodeError):
                unchanged = False
            allowed_env = set(env) <= {"PATH", "HOME", "PYTHONDONTWRITEBYTECODE", "LANG"}
            required_flags = {
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user=65534:65534",
                "--memory=512m",
                "--pids-limit=64",
            }
            contract = (
                (
                    required_flags.issubset(command)
                    and command.count("--mount") == 1
                    and mount_names == {"notebook.py"}
                    and f"type=bind,src={sandbox.resolve()},dst=/submission,readonly" in command
                )
                if self.mode == "docker"
                else (source in (self.registry.reference_source(task), self.registry.negative_source(task)))
            )
            result.checks.append(
                CheckResult(
                    name="integrity",
                    passed=bool(unchanged and allowed_env and contract and not result.infrastructure_error),
                    detail="Checks submitted source hash, launch isolation flags, single read-only source mount, and credential-free launch environment. "
                    "Trusted-reference mode checks the exact authored-source allowlist instead. This is not a proof against all runtime exploits.",
                )
            )
            result.success = result.success and result.checks[-1].passed
            commands = [["docker", "rm", "-f", name]] if self.mode == "docker" else []
            cleanup = asyncio.create_task(_cleanup(process, commands))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await _drain(cleanup)
                raise
            result.duration_ms = (time.monotonic() - started) * 1000
        return result

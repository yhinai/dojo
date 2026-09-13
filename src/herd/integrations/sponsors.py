"""Live, secret-safe sponsor baseline checks."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from herd.config import ROOT, wandb_project


def _result(status: str, detail: str, **evidence):
    return {"status": status, "detail": detail, **evidence}


def _openai_provider(base_url: str, api_key: str, model: str, project: str = "") -> dict:
    if not api_key:
        return _result("pending", "credential is not configured")
    if not base_url or not model:
        return _result("pending", "endpoint and model must be configured")
    if urlparse(base_url).scheme != "https":
        return _result("fail", "provider endpoint must use HTTPS")
    headers = {"Authorization": f"Bearer {api_key}"}
    if project:
        headers["OpenAI-Project"] = project
    try:
        response = httpx.get(base_url.rstrip("/") + "/models", headers=headers, timeout=30)
        if response.status_code != 200:
            return _result("fail", f"models endpoint returned HTTP {response.status_code}")
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            return _result("fail", "models endpoint returned an invalid response shape")
        models = [item.get("id") for item in data]
        if model not in models:
            return _result("fail", "configured model is absent from the authenticated model list", model=model)
        completion = httpx.post(
            base_url.rstrip("/") + "/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: baseline-ok"}],
                "max_tokens": 64,
                "temperature": 0,
                "stream": False,
            },
            timeout=60,
        )
        if completion.status_code != 200:
            return _result("fail", f"completion endpoint returned HTTP {completion.status_code}", model=model)
        payload = completion.json()
        usage = payload.get("usage", {})
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            return _result("fail", "completion succeeded but returned no visible content", model=model)
        return _result(
            "pass",
            "authenticated model listing and minimal completion succeeded",
            model=model,
            model_count=len(models),
            response_nonempty=True,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        return _result("fail", f"provider check failed: {type(exc).__name__}")


def sponsor_baseline(*, publish_weave: bool = False) -> dict:
    """Exercise every documented integration without returning credential values."""
    checks: dict[str, dict] = {}

    try:
        import wandb

        viewer = wandb.Api(timeout=30).viewer
        checks["wandb"] = _result(
            "pass", "API authentication succeeded", username=getattr(viewer, "username", None)
        )
    except Exception as exc:  # noqa: BLE001 - report optional external-service failure
        checks["wandb"] = _result("fail", f"API authentication failed: {type(exc).__name__}")

    project = wandb_project()
    try:
        import weave

        weave.init(project)
        evidence = {"project": project}
        if publish_weave:
            ref = weave.publish(
                {"kind": "sponsor_baseline", "checked_at": datetime.now(UTC).isoformat()},
                name="herd-sponsor-baseline",
            )
            evidence["remote_ref"] = ref.uri()
        checks["weave"] = _result("pass", "Weave authentication succeeded", **evidence)
    except Exception as exc:  # noqa: BLE001
        checks["weave"] = _result("fail", f"Weave initialization failed: {type(exc).__name__}", project=project)

    inference_key = os.getenv("HERD_INFERENCE_API_KEY") or os.getenv("WANDB_API_KEY", "")
    checks["wandb_inference"] = _openai_provider(
        os.getenv("HERD_INFERENCE_BASE_URL", "https://api.inference.wandb.ai/v1"),
        inference_key,
        os.getenv("HERD_MODEL", "deepseek-ai/DeepSeek-V4-Flash-0731"),
        project,
    )

    command = [str(ROOT / ".venv/bin/marimo"), "check", str(ROOT / "app/control_room.py")]
    if not Path(command[0]).exists():
        command[0] = "marimo"
    try:
        checked = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        checks["marimo"] = _result(
            "pass" if checked.returncode == 0 else "fail",
            "control-room notebook passes marimo check"
            if checked.returncode == 0
            else "control-room notebook failed marimo check",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks["marimo"] = _result("fail", f"marimo check failed: {type(exc).__name__}")

    checks["molab"] = _result(
        "manual",
        "Google-authenticated hosted notebook and GPU must be verified in the molab UI",
        notebook="https://molab.marimo.io/notebooks/nb_RN9cswq5rokKqs9eyB1GyQ",
    )
    checks["aria"] = _result(
        "manual" if checks["wandb"]["status"] == "pass" else "fail",
        "ARIA uses the authenticated W&B UI and the implemented export/import handoff; it has no separate API key",
    )
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "summary": {
            status: sum(item["status"] == status for item in checks.values())
            for status in ("pass", "fail", "pending", "manual")
        },
    }

"""Authenticated operator controls over durable experiment state."""

from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from herd.store import Store


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["retract", "rollback", "supersede", "resolve_conflict"]
    reason: str = Field(min_length=12, max_length=2000)
    lesson_ids: list[str] = Field(default_factory=list, max_length=30)
    target_pool_hash: str | None = None
    replacement_id: str | None = None


class Curriculum(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str
    track_weights: dict[str, int]
    reason: str = Field(min_length=12, max_length=2000)


class Reconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    actual_usd: float = Field(ge=0, allow_inf_nan=False)
    evidence: str = Field(min_length=12, max_length=4000)
    actor: str = Field(min_length=1, max_length=200)
    authorize_retry: bool = False


def create_app(store: Store | None = None, engine=None, demo=False):
    store = store or Store(Path(os.getenv("HERD_STATE_DIR", "experiments")) / "herd.sqlite3")
    running = {}

    @asynccontextmanager
    async def lifespan(app):
        with store.maintenance_lock():
            store.reconcile_abandoned()
            try:
                yield
            finally:
                for task in running.values():
                    if not task.done():
                        task.cancel()
                if running:
                    await asyncio.gather(*running.values(), return_exceptions=True)

    app = FastAPI(title="HERD", version="0.1.0", lifespan=lifespan)
    app.state.running = running
    private_reads = os.getenv("HERD_AUTH_READS", "0").lower() in {"1", "true", "yes"}

    @app.middleware("http")
    async def read_auth(request: Request, call_next):
        if private_reads and request.method == "GET" and request.url.path != "/api/health":
            expected = os.getenv("HERD_CONTROL_TOKEN")
            token = request.headers.get("x-herd-token")
            if not expected or not token or not secrets.compare_digest(token, expected):
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "Authenticated evidence access required"}, status_code=401)
        return await call_next(request)

    def experiment(eid):
        value = store.get(eid, "experiment", eid)
        if not value:
            raise HTTPException(404, "Unknown experiment")
        return value

    def authorize(token, need_engine=True):
        if demo:
            raise HTTPException(403, "Demo mode is read-only")
        expected = os.getenv("HERD_CONTROL_TOKEN")
        if not expected or not token or not secrets.compare_digest(token, expected):
            raise HTTPException(401, "Set HERD_CONTROL_TOKEN and provide X-Herd-Token")
        if need_engine and engine is None:
            raise HTTPException(503, "Worker engine is not configured")

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/api/health")
    def health():
        return {"status": "ok" if store.health()["database"] == "ok" else "degraded", "demo": demo}

    @app.get("/api/experiments")
    def experiments(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        return store.experiments(limit, offset)

    @app.get("/api/readiness")
    async def readiness():
        from fastapi.responses import JSONResponse

        from herd.config import runtime_readiness

        checks = await asyncio.to_thread(runtime_readiness, engine)
        checks["database_healthy"] = store.health()["database"] == "ok"
        checks["runtime_preflight_ready"] = False
        checks["browser_launch_ready"] = False
        evaluator = getattr(getattr(engine, "learner", None), "evaluator", None)
        if evaluator is not None:
            try:
                runtime = await evaluator.preflight(browser=True)
                checks["runtime_preflight_ready"] = bool(
                    runtime.get("ready") and runtime.get("secure_for_generated_code")
                )
                checks["browser_launch_ready"] = bool(runtime.get("browser", {}).get("ready"))
            except Exception:  # noqa: BLE001 - readiness must report unavailable dependencies without crashing
                checks["runtime_preflight_ready"] = False
        ready = all(checks.values()) and not demo
        return JSONResponse(
            {"ready": ready, "checks": checks, "demo": demo}, status_code=200 if ready else 503
        )

    collection_kinds = {
        "lesson",
        "gate",
        "pair",
        "weave_link",
        "lifecycle",
        "curriculum",
        "draft_review",
        "poisoning_control",
        "control_gate",
        "lesson_history",
        "aria_analysis",
        "calibration",
    }

    @app.get("/api/experiments/{eid}/collections/{kind}")
    def collection(eid: str, kind: str, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        experiment(eid)
        if kind not in collection_kinds:
            raise HTTPException(404, "Unknown evidence collection")
        return store.page(eid, kind, limit, offset)

    @app.get("/api/experiments/{eid}")
    def details(eid: str):
        exp = experiment(eid)
        head = store.get(eid, "head", "current", {})
        page = store.page(eid, "attempt", 100)
        return {
            "experiment": exp,
            "attempts": [attempt_summary(a) for a in page["items"]],
            "attempt_page": {k: v for k, v in page.items() if k != "items"},
            **{
                plural: store.page(eid, singular, 100)["items"]
                for plural, singular in [
                    ("lessons", "lesson"),
                    ("gates", "gate"),
                    ("weave_links", "weave_link"),
                    ("lifecycle_requests", "lifecycle"),
                    ("curriculum_decisions", "curriculum"),
                    ("draft_reviews", "draft_review"),
                    ("negative_controls", "poisoning_control"),
                    ("control_gates", "control_gate"),
                    ("lesson_history", "lesson_history"),
                ]
            },
            "collection_pages": {
                kind: {k: v for k, v in store.page(eid, kind, 100).items() if k != "items"}
                for kind in collection_kinds
            },
            "control": store.control(eid),
            "pool": store.get(eid, "pool", head.get("pool_hash", "")),
            "events": [],
            "report": None,
            "report_available": store.get(eid, "report", "current") is not None,
        }

    def attempt_summary(value):
        return {
            key: value.get(key)
            for key in (
                "run_id",
                "task_id",
                "learner_id",
                "logical_learner_id",
                "retry_of",
                "round_id",
                "arm",
                "status",
                "pool_hash",
                "first_submission_success",
                "submissions",
                "tool_calls",
                "input_tokens",
                "output_tokens",
                "cost_usd",
                "mode",
                "started_at",
                "completed_at",
                "retrieved_lesson_ids",
            )
        } | {
            "result": {k: value["result"].get(k) for k in ("success", "infrastructure_error", "duration_ms")}
            if value.get("result")
            else None
        }

    @app.get("/api/experiments/{eid}/attempts")
    def attempts(eid: str, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        experiment(eid)
        page = store.page(eid, "attempt", limit, offset)
        page["items"] = [attempt_summary(a) for a in page["items"]]
        return page

    @app.get("/api/experiments/{eid}/attempts/{run_id}")
    def attempt_artifact(eid: str, run_id: str):
        experiment(eid)
        record = store.get(eid, "attempt", run_id)
        if not record:
            raise HTTPException(404, "Unknown attempt")
        return record

    @app.get("/api/experiments/{eid}/events")
    def events(eid: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
        experiment(eid)
        return store.event_page(eid, after, limit)

    @app.get("/api/experiments/{eid}/failure-clusters")
    def failure_clusters(eid: str):
        experiment(eid)
        from herd.reports import first_failure_clusters

        return first_failure_clusters(
            store.list(eid, "attempt"),
            {t["task_id"] for t in store.list(eid, "task") if t["partition"] == "development"},
        )

    @app.get("/api/experiments/{eid}/report")
    def report(eid: str):
        experiment(eid)
        return store.get(eid, "report", "current")

    @app.get("/api/experiments/{eid}/pool")
    def pool(eid: str):
        experiment(eid)
        return store.get(eid, "pool", store.get(eid, "head", "current", {}).get("pool_hash", ""))

    @app.post("/api/experiments")
    def create(x_herd_token: str | None = Header(default=None)):
        authorize(x_herd_token)
        return engine.create()

    @app.post("/api/experiments/{eid}/start")
    @app.post("/api/experiments/{eid}/resume")
    async def start(eid: str, x_herd_token: str | None = Header(default=None)):
        authorize(x_herd_token)
        experiment(eid)
        if eid in running and not running[eid].done():
            return {"status": "running", "control": store.control(eid)}
        try:
            with store.execution_lock():
                store.request_control(eid, "resume")
        except RuntimeError:
            raise HTTPException(409, "A scheduler already owns this state directory") from None

        async def execute():
            try:
                await engine.run(eid)
            except Exception as exc:  # noqa: BLE001 — scheduler task boundary; record only exception type
                store.event(eid, "worker.stopped", {"error_type": type(exc).__name__})

        running[eid] = asyncio.create_task(execute())
        return {"status": "started"}

    @app.post("/api/experiments/{eid}/pause")
    @app.post("/api/experiments/{eid}/cancel")
    async def stop(eid: str, request: Request, x_herd_token: str | None = Header(default=None)):
        authorize(x_herd_token, need_engine=False)
        exp = experiment(eid)
        action = request.url.path.rsplit("/", 1)[-1]
        command = store.request_control(eid, action)
        try:
            with store.execution_lock():
                store.put(
                    eid,
                    "experiment",
                    eid,
                    {**exp, "status": "paused" if action == "pause" else "cancelled"},
                    expected=exp,
                )
        except RuntimeError:
            pass  # An API or external CLI scheduler will apply the command at its checkpoint.
        return {
            "status": f"{action}_requested",
            "control": command,
            "detail": "Stops at the next safe checkpoint; in-flight provider reservations remain charged.",
        }

    @app.post("/api/experiments/{eid}/lifecycle")
    def lifecycle(eid: str, body: Change, x_herd_token: str | None = Header(default=None)):
        authorize(x_herd_token, need_engine=False)
        experiment(eid)
        from herd.lifecycle import request_change

        return request_change(store, eid, **body.model_dump())

    @app.post("/api/experiments/{eid}/curriculum")
    def curriculum(eid: str, body: Curriculum, x_herd_token: str | None = Header(default=None)):
        authorize(x_herd_token, need_engine=False)
        experiment(eid)
        from herd.curriculum import queue_curriculum

        return queue_curriculum(store, eid, **body.model_dump())

    @app.post("/api/budget/reconcile")
    def reconcile(body: Reconciliation, x_herd_token: str | None = Header(default=None)):
        authorize(x_herd_token)
        gateway = getattr(getattr(engine, "learner", None), "gateway", None) or getattr(
            engine, "gateway", None
        )
        ledger = getattr(gateway, "ledger", None)
        if ledger is None:
            raise HTTPException(503, "Inference ledger unavailable")
        from herd.gateway import GatewayError

        try:
            return ledger.reconcile(**body.model_dump())
        except GatewayError as exc:
            raise HTTPException(409, str(exc)) from None

    return app

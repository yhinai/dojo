"""Authenticated operator controls over durable experiment state."""

from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
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
    def experiments():
        return store.experiments()

    @app.get("/api/experiments/{eid}")
    def details(eid: str):
        exp = experiment(eid)
        head = store.get(eid, "head", "current", {})
        return {
            "experiment": exp,
            **{
                plural: store.list(eid, singular)
                for plural, singular in [
                    ("attempts", "attempt"),
                    ("lessons", "lesson"),
                    ("gates", "gate"),
                    ("pairs", "pair"),
                    ("weave_links", "weave_link"),
                    ("lifecycle_requests", "lifecycle"),
                    ("curriculum_decisions", "curriculum"),
                    ("draft_reviews", "draft_review"),
                    ("negative_controls", "poisoning_control"),
                    ("control_gates", "control_gate"),
                    ("lesson_history", "lesson_history"),
                ]
            },
            "control": store.control(eid),
            "pool": store.get(eid, "pool", head.get("pool_hash", "")),
            "events": store.events(eid),
            "report": store.get(eid, "report", "current"),
        }

    @app.get("/api/experiments/{eid}/events")
    def events(eid: str):
        experiment(eid)
        return store.events(eid)

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
        store.request_control(eid, "resume")

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
        if eid not in running or running[eid].done():
            store.put(
                eid,
                "experiment",
                eid,
                {**exp, "status": "paused" if action == "pause" else "cancelled"},
                expected=exp,
            )
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

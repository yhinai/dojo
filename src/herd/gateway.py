"""Bounded OpenAI-compatible inference with crash-safe dollar reservations."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .schemas import digest, utcnow


class BudgetExceeded(RuntimeError):
    pass


class GlobalBudgetExceeded(BudgetExceeded):
    pass


class GatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayConfig:
    model: str = "deepseek-ai/DeepSeek-V4-Flash-0731"
    base_url: str = "https://api.inference.wandb.ai/v1"
    api_key: str = field(default="", repr=False)
    project: str = ""
    input_per_million: float = 0.13
    output_per_million: float = 0.28
    cap_usd: float = 25.0
    pricing_source: str = "https://site.wandb.ai/pricing/tokens/"
    pricing_verified_at: str = "2026-09-13"
    timeout_seconds: float = 65

    def __post_init__(self):
        numbers = (self.input_per_million, self.output_per_million, self.cap_usd, self.timeout_seconds)
        if any(not math.isfinite(v) or v <= 0 for v in numbers):
            raise ValueError("Pricing, cap and timeout must be finite and positive")
        if urlparse(self.base_url).scheme != "https":
            raise ValueError("Provider URL must use HTTPS")

    @classmethod
    def from_env(cls):
        default_model = cls.model
        model = os.getenv("HERD_MODEL", default_model)
        base_url = os.getenv("HERD_INFERENCE_BASE_URL", cls.base_url)
        if (model != default_model or base_url != cls.base_url) and not all(
            os.getenv(k)
            for k in (
                "HERD_INPUT_PRICE_PER_MILLION",
                "HERD_OUTPUT_PRICE_PER_MILLION",
                "HERD_PRICING_SOURCE",
                "HERD_PRICING_VERIFIED_AT",
            )
        ):
            raise ValueError("A different model/provider requires explicit verified pricing")
        return cls(
            model=model,
            base_url=base_url,
            api_key=os.getenv("HERD_INFERENCE_API_KEY") or os.getenv("WANDB_API_KEY", ""),
            project=os.getenv("WANDB_PROJECT", ""),
            input_per_million=float(os.getenv("HERD_INPUT_PRICE_PER_MILLION", ".13")),
            output_per_million=float(os.getenv("HERD_OUTPUT_PRICE_PER_MILLION", ".28")),
            cap_usd=float(os.getenv("HERD_DOLLAR_CAP", "25")),
            pricing_source=os.getenv("HERD_PRICING_SOURCE", cls.pricing_source),
            pricing_verified_at=os.getenv("HERD_PRICING_VERIFIED_AT", cls.pricing_verified_at),
        )

    def public_dict(self):
        return {k: v for k, v in self.__dict__.items() if k != "api_key"}

    @property
    def config_hash(self):
        return digest({"model": self.model, "base_url": self.base_url, "temperature": 0.2})


class BudgetLedger:
    """Reservations survive crashes. Unknown outcomes stay fully charged; never auto-retry."""

    def __init__(self, path: str | Path, cap_usd: float):
        if not math.isfinite(cap_usd) or cap_usd <= 0:
            raise ValueError("Positive finite cap required")
        self.path, self.cap_usd = str(path), cap_usd
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS inference_budget (request_id TEXT PRIMARY KEY, "
                "reserved REAL NOT NULL, charged REAL, status TEXT NOT NULL)"
            )

            db.execute(
                "CREATE TABLE IF NOT EXISTS inference_completions (request_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

            db.execute(
                "CREATE TABLE IF NOT EXISTS inference_bindings (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)"
            )

    def entries(self, request_prefixes=None):
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute("SELECT * FROM inference_budget ORDER BY rowid")]
        if request_prefixes is not None:
            rows = [r for r in rows if any(r["request_id"].startswith(p + ":") for p in request_prefixes)]
        return rows

    def reconcile(self, request_id, actual_usd, evidence, actor, authorize_retry=False):
        """Resolve uncertain billing only against an explicit operator/provider evidence reference."""
        if not math.isfinite(actual_usd) or actual_usd < 0:
            raise ValueError("Actual charge must be finite and nonnegative")
        if len(evidence.strip()) < 12 or not actor.strip():
            raise ValueError("Operator identity and provider billing evidence are required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT reserved,status,charged FROM inference_budget WHERE request_id=?", (request_id,)
            ).fetchone()
            if row and row[1] == "reconciled" and authorize_retry and actual_usd == row[2]:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS inference_retry_authorizations (request_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                )
                amendment = {
                    "request_id": request_id,
                    "actual_usd": actual_usd,
                    "evidence": evidence,
                    "actor": actor,
                    "authorize_retry": True,
                    "authorized_at": utcnow(),
                }
                old = db.execute(
                    "SELECT payload FROM inference_retry_authorizations WHERE request_id=?", (request_id,)
                ).fetchone()
                if old:
                    return json.loads(old[0])
                db.execute(
                    "INSERT INTO inference_retry_authorizations VALUES(?,?)",
                    (request_id, json.dumps(amendment)),
                )
                return amendment
            if row is None or row[1] != "reserved":
                raise GatewayError("Only an unresolved reservation can be reconciled")
            db.execute(
                "CREATE TABLE IF NOT EXISTS inference_reconciliations (request_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            record = {
                "request_id": request_id,
                "reserved_usd": row[0],
                "actual_usd": actual_usd,
                "evidence": evidence,
                "actor": actor,
                "authorize_retry": authorize_retry,
                "reconciled_at": utcnow(),
            }
            db.execute("INSERT INTO inference_reconciliations VALUES(?,?)", (request_id, json.dumps(record)))
            db.execute(
                "UPDATE inference_budget SET charged=?,status='reconciled' WHERE request_id=?",
                (actual_usd, request_id),
            )
        return record

    def physical_request_id(self, logical_id):
        """Only explicitly reconciled requests may advance to a new billed generation."""
        with self._connect() as db:
            request_id = logical_id
            for generation in range(100):
                row = db.execute(
                    "SELECT status FROM inference_budget WHERE request_id=?", (request_id,)
                ).fetchone()
                if row is None or row[0] != "reconciled":
                    return request_id
                audit = db.execute(
                    "SELECT payload FROM inference_reconciliations WHERE request_id=?", (request_id,)
                ).fetchone()
                db.execute(
                    "CREATE TABLE IF NOT EXISTS inference_retry_authorizations (request_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                )
                amendment = db.execute(
                    "SELECT payload FROM inference_retry_authorizations WHERE request_id=?", (request_id,)
                ).fetchone()
                if not amendment and (not audit or not json.loads(audit[0]).get("authorize_retry")):
                    raise GatewayError(
                        "Reconciled request has no result; operator must explicitly authorize a new billed retry"
                    )
                request_id = f"{logical_id}:retry:{generation + 1}"
            raise GatewayError("Retry generation limit reached")

    def bind(self, request_id, fingerprint):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT fingerprint FROM inference_bindings WHERE request_id=?", (request_id,)
            ).fetchone()
            if old and old[0] != fingerprint:
                raise GatewayError("Request ID is already bound to different inputs")
            db.execute("INSERT OR IGNORE INTO inference_bindings VALUES(?,?)", (request_id, fingerprint))

    def cached(self, request_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM inference_completions WHERE request_id=?", (request_id,)
            ).fetchone()
        return Completion(**json.loads(row[0])) if row else None

    def cache(self, request_id, completion):
        with self._connect() as db:
            db.execute(
                "INSERT INTO inference_completions VALUES(?,?)", (request_id, json.dumps(completion.__dict__))
            )

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def reserve(self, request_id: str, amount: float):
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Invalid reservation")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute(
                "SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM inference_budget"
            ).fetchone()[0]
            if total + amount > self.cap_usd + 1e-12:
                raise GlobalBudgetExceeded("Global inference dollar cap reached")
            try:
                db.execute("INSERT INTO inference_budget VALUES(?,?,NULL,'reserved')", (request_id, amount))
            except sqlite3.IntegrityError:
                raise GatewayError("Request already reserved; reconcile before retrying") from None

    def settle(self, request_id: str, actual: float, completion=None, cache_key=None):
        if not math.isfinite(actual) or actual < 0:
            raise ValueError("Invalid charge")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT reserved,status FROM inference_budget WHERE request_id=?", (request_id,)
            ).fetchone()
            if not row or row[1] != "reserved":
                raise GatewayError("Reservation missing or already settled")
            db.execute(
                "UPDATE inference_budget SET charged=?,status='settled' WHERE request_id=?",
                (actual, request_id),
            )
            if completion is not None:
                db.execute(
                    "INSERT INTO inference_completions VALUES(?,?)",
                    (cache_key or request_id, json.dumps(completion.__dict__)),
                )
        if actual > row[0] + 1e-12:
            raise GatewayError("Provider usage exceeded conservative reservation; execution stopped")

    def summary(self, request_prefixes=None):
        rows = self.entries(request_prefixes)
        total = sum(r["charged"] if r["charged"] is not None else r["reserved"] for r in rows)
        return {
            "cap_usd": self.cap_usd,
            "committed_usd": total,
            "settled_usd": sum(r["charged"] or 0 for r in rows),
            "reserved_usd": sum(r["reserved"] for r in rows if r["charged"] is None),
            "pending_requests": sum(r["status"] == "reserved" for r in rows),
            "remaining_usd": max(0, self.cap_usd - total),
        }


@dataclass
class Completion:
    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def input_token_bound(messages: list[dict[str, Any]]) -> int:
    # Byte count deliberately over-reserves across provider tokenizers; include chat framing margin.
    return len(json.dumps(messages, ensure_ascii=False).encode()) + 256 * (len(messages) + 1)


class ProviderGateway:
    mode = "measured"

    def __init__(self, config: GatewayConfig, ledger: BudgetLedger, transport=None):
        self.config, self.ledger, self.transport = config, ledger, transport

    async def complete(
        self,
        messages: list[dict],
        max_output_tokens: int,
        request_id: str,
        max_input_tokens: int | None = None,
    ) -> Completion:
        self.ledger.bind(request_id, digest([self.config.config_hash, messages, max_output_tokens]))
        cached = self.ledger.cached(request_id)
        if cached:
            return cached
        if not self.config.api_key:
            raise GatewayError("Configure WANDB_API_KEY or HERD_INFERENCE_API_KEY locally")
        bound = input_token_bound(messages)
        if max_output_tokens <= 0 or (max_input_tokens is not None and bound > max_input_tokens):
            raise BudgetExceeded("Episode token budget cannot fit this request")
        reserve = (
            bound * self.config.input_per_million + max_output_tokens * self.config.output_per_million
        ) / 1_000_000
        physical_id = self.ledger.physical_request_id(request_id)
        self.ledger.reserve(physical_id, reserve)
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        if self.config.project:
            headers["OpenAI-Project"] = self.config.project
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    self.config.base_url.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json={
                        "model": self.config.model,
                        "messages": messages,
                        "max_tokens": max_output_tokens,
                        "temperature": 0.2,
                        "stream": False,
                    },
                )
            if response.status_code != 200:
                raise GatewayError(f"Provider HTTP {response.status_code}; reservation retained")
            data = response.json()
            usage = data["usage"]
            inp, out = int(usage["prompt_tokens"]), int(usage["completion_tokens"])
            if inp < 0 or out < 0:
                raise ValueError("Invalid usage")
            cost = (inp * self.config.input_per_million + out * self.config.output_per_million) / 1_000_000
            if inp > bound or out > max_output_tokens:
                raise GatewayError("Provider exceeded requested token bound")
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("Missing content")
            completion = Completion(content, inp, out, cost)
            self.ledger.settle(physical_id, cost, completion, cache_key=request_id)
            return completion
        except GatewayError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            # Never echo provider response/request: it may contain credentials or private server diagnostics.
            raise GatewayError(
                "Provider response unavailable or invalid; reserved cost retained if unresolved"
            ) from None

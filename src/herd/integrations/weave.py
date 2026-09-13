"""Weave native evaluations plus durable content-addressed upload outbox.

No connection occurs at import. Recorded evaluations replay oracle results, not
model executions, and are labeled accordingly. Local run IDs retain provenance.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from herd.schemas import AttemptRecord, digest, utcnow


def behavioral_scores(output: dict, category: str | None = None) -> dict:
    result = output.get("result")
    if not result:
        return {"available": False, "passed": None, "local_run_id": output.get("run_id")}
    checks = result.get("checks", [])
    aliases = {
        "structure": ("structure", "syntax"),
        "startup": ("startup", "launch"),
        "semantic_probe": ("semantic", "behavior", "function"),
        "interaction_probe": ("interaction", "widget", "browser"),
        "integrity": ("integrity", "isolation", "tamper"),
    }
    if category:
        checks = [c for c in checks if any(tag in c["name"].lower() for tag in aliases[category])]
    return {
        "available": bool(checks),
        "passed": (all(c["passed"] for c in checks) and not result.get("infrastructure_error"))
        if checks
        else None,
        "local_run_id": output.get("run_id"),
        "artifact_hash": result.get("artifact_hash"),
        "check_count": len(checks),
    }


class WeaveIntegration:
    def __init__(self, project: str | None, state_dir: str | Path):
        self.project = project
        directory = Path(state_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "weave-outbox.sqlite3"
        self.client = None
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS uploads (key TEXT PRIMARY KEY, kind TEXT, payload TEXT, "
                "status TEXT, remote_ref TEXT, error TEXT, attempts INTEGER DEFAULT 0)"
            )

    def _db(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def enqueue(self, kind: str, key: str, payload: dict) -> str:
        data = json.dumps(payload, sort_keys=True)
        with self._db() as db:
            existing = db.execute("SELECT payload,kind FROM uploads WHERE key=?", (key,)).fetchone()
            if existing and (existing["payload"] != data or existing["kind"] != kind):
                raise ValueError("outbox key already bound to different content")
            db.execute(
                "INSERT OR IGNORE INTO uploads(key,kind,payload,status) VALUES (?,?,?,?)",
                (key, kind, data, "pending"),
            )
        return key

    def status(self) -> list[dict]:
        with self._db() as db:
            return [
                dict(row)
                for row in db.execute("SELECT key,kind,status,remote_ref,error,attempts FROM uploads")
            ]

    def connect(self):
        if not self.project:
            raise RuntimeError("W&B project is unconfigured; local evidence remains pending")
        import weave

        if self.client is None:
            self.client = weave.init(self.project)
        return weave

    def flush(self) -> dict:
        """Publish immutable evidence objects; same key/content gives same object version.

        Publish is content-addressed; a crash before acknowledgement may repeat the
        request but cannot create a different evidence identity. No invented trace URL.
        """
        uploaded = 0
        for item in self.status():
            if item["status"] == "uploaded":
                continue
            try:
                weave = self.connect()
                with self._db() as db:
                    row = db.execute("SELECT * FROM uploads WHERE key=?", (item["key"],)).fetchone()
                payload = {
                    "local_evidence_id": row["key"],
                    "kind": row["kind"],
                    "evidence": json.loads(row["payload"]),
                }
                ref = weave.publish(sanitize_trace(payload), name=f"herd-evidence-{digest(row['key'])[:24]}")
                with self._db() as db:
                    db.execute(
                        "UPDATE uploads SET status='uploaded',remote_ref=?,error=NULL,attempts=attempts+1 WHERE key=?",
                        (ref.uri(), row["key"]),
                    )
                uploaded += 1
            except Exception as exc:  # noqa: BLE001 - optional SDK outages remain pending
                with self._db() as db:
                    db.execute(
                        "UPDATE uploads SET error=?,attempts=attempts+1 WHERE key=?",
                        (f"{type(exc).__name__}: upload failed; inspect local configuration", item["key"]),
                    )
                break
        return {"uploaded": uploaded, "items": self.status()}

    async def evaluate_attempts(self, name: str, attempts: list[AttemptRecord]) -> dict:
        """Upload native Evaluation per pool/arm, rescoring actual recorded outputs.

        This makes no model calls. Its replay label distinguishes upload time from
        execution time. Every row includes its original run ID and behavioral evidence.
        """
        if not attempts:
            raise ValueError("cannot evaluate an empty attempt stream")
        if any(a.mode != "measured" for a in attempts):
            raise ValueError("fixture attempts must not be published as measured evaluations")
        weave = self.connect()

        class BehaviorScorer(weave.Scorer):
            category: str | None = None

            @weave.op()
            def score(self, output: dict) -> dict:
                return behavioral_scores(output, self.category)

        class RecordedWorker(weave.Model):
            pool_hash: str
            arm: str
            execution_mode: str = "recorded_oracle_replay"
            records: dict[str, dict]

            @weave.op()
            def predict(self, run_key: str) -> dict:
                return self.records[run_key]

        # A candidate stream shares one dataset keyed by task/repeat across arms.
        grouped: dict[tuple[str, str], dict] = {}
        for attempt in attempts:
            group = grouped.setdefault((attempt.pool_hash, attempt.arm), {})
            key = f"{attempt.task_id}:{attempt.logical_learner_id or attempt.learner_id}"
            if key in group:
                raise ValueError("duplicate task/repeat in evaluation arm")
            group[key] = attempt.model_dump(mode="json", exclude={"messages", "source", "initial_source"})
        common = set.intersection(*(set(records) for records in grouped.values()))
        if not common:
            raise ValueError("evaluation arms have no matched task/repeat keys")
        scorers = [BehaviorScorer(name="behavior")]
        scorers += [
            BehaviorScorer(name=category, category=category)
            for category in ("structure", "startup", "semantic_probe", "interaction_probe", "integrity")
        ]
        evaluation = weave.Evaluation(
            name=name, dataset=[{"run_key": key} for key in sorted(common)], scorers=scorers
        )
        results = {}
        for (pool, arm), records in grouped.items():
            results[f"{pool}:{arm}"] = await evaluation.evaluate(
                RecordedWorker(name=f"pool-{pool[:12]}-{arm}", pool_hash=pool, arm=arm, records=records)
            )
        from weave.trace.ref_util import get_ref

        ref = get_ref(evaluation)
        return {
            "evaluation_ref": ref.uri() if ref else None,
            "mode": "recorded_oracle_replay",
            "matched_rows": len(common),
            "results": results,
            "uploaded_at": utcnow(),
        }

    def publish_leaderboard(self, evaluation_refs: list[str], name: str = "HERD pool versions") -> str:
        if not evaluation_refs:
            raise ValueError("leaderboard requires authentic evaluation object references")
        weave = self.connect()
        from weave.flow.leaderboard import Leaderboard, LeaderboardColumn

        board = Leaderboard(
            name=name,
            description="Recorded behavioral evaluations. Models bind immutable pool hashes.",
            columns=[
                LeaderboardColumn(
                    evaluation_object_ref=ref,
                    scorer_name="behavior",
                    summary_metric_path="passed.true_fraction",
                )
                for ref in evaluation_refs
            ],
        )
        return weave.publish(board).uri()

    async def sync_store(self, store, experiment_id: str, *, upload: bool = True) -> dict:
        """Recover evidence from durable state; content revisions have independent identities.

        A periodic sweep means crashes between the source commit and enqueue cannot
        lose evidence. Remote references are persisted only after real acknowledgement.
        """
        if any(a.get("mode") != "measured" for a in store.list(experiment_id, "attempt")):
            return {"status": "fixture_experiment_excluded", "queued": 0, "uploaded": 0}
        kinds = (
            "attempt",
            "pool",
            "gate",
            "pair",
            "report",
            "lesson",
            "poisoning_control",
            "control_gate",
            "control_pair",
            "curriculum",
            "aria_analysis",
            "draft_review",
            "pair_retry",
            "runtime_retry",
            "live_evaluation",
            "control_recovery",
            "lifecycle",
        )
        index = {}
        for kind in kinds:
            for value in store.list(experiment_id, kind):
                if value.get("mode") in {"test", "fixture"}:
                    continue
                content_hash = digest(value)
                key = f"{experiment_id}-{kind}-{content_hash}"
                self.enqueue(kind, key, value)
                identity = next(
                    (
                        value[k]
                        for k in (
                            "run_id",
                            "trial_id",
                            "pair_id",
                            "lesson_id",
                            "report_hash",
                            "pool_hash",
                            "id",
                        )
                        if value.get(k)
                    ),
                    content_hash,
                )
                index[key] = {"kind": kind, "local_id": identity, "content_hash": content_hash}
        if not upload or not self.project or not os.getenv("WANDB_API_KEY"):
            return {"status": "pending_configuration", "queued": len(index), "uploaded": 0}
        result = self.flush()
        for item in result["items"]:
            if item["key"] not in index or not item["remote_ref"]:
                continue
            record = {**index[item["key"]], "remote_ref": item["remote_ref"], "status": "uploaded"}
            if store.get(experiment_id, "weave_link", item["key"]) != record:
                store.put(experiment_id, "weave_link", item["key"], record)
        attempts = {
            a["run_id"]: a for a in store.list(experiment_id, "attempt") if a.get("mode") == "measured"
        }
        pairs = store.list(experiment_id, "pair") + store.list(experiment_id, "control_pair")
        groups = []
        for gate in store.list(experiment_id, "gate") + store.list(experiment_id, "control_gate"):
            if gate["decision"] == "evaluating":
                continue
            records = []
            for pair in pairs:
                if pair["pair_id"] not in gate["pair_ids"]:
                    continue
                for field in ("control_run_id", "treatment_run_id"):
                    if pair[field] in attempts:
                        records.append({**attempts[pair[field]], "learner_id": pair["pair_id"]})
            if records:
                groups.append((gate["trial_id"], records))
        final_tasks = {t["task_id"] for t in store.list(experiment_id, "task") if t["partition"] == "final"}
        for report in store.list(experiment_id, "report"):
            records = [
                a
                for a in attempts.values()
                if a["task_id"] in final_tasks
                and a.get("status") != "infrastructure_error"
                and not (a.get("result") and a["result"].get("infrastructure_error"))
            ]
            if records:
                groups.append((f"final-{report['pool_hash']}", records))
        refs = []
        for local_id, records in groups:
            binding = digest(records)
            saved = store.get(experiment_id, "weave_evaluation", local_id)
            if saved and saved.get("content_hash") == binding and saved.get("evaluation_ref"):
                refs.append(saved["evaluation_ref"])
                continue
            try:
                evaluated = await self.evaluate_attempts(
                    f"herd-{digest([experiment_id, local_id])[:24]}",
                    [AttemptRecord.model_validate(a) for a in records],
                )
                evaluated.update(local_id=local_id, content_hash=binding, status="uploaded")
                store.put(experiment_id, "weave_evaluation", local_id, evaluated)
                if evaluated.get("evaluation_ref"):
                    refs.append(evaluated["evaluation_ref"])
            except Exception as exc:  # noqa: BLE001 - preserve optional SDK failure for retry
                store.put(
                    experiment_id,
                    "weave_evaluation",
                    local_id,
                    {"status": "pending", "content_hash": binding, "error": type(exc).__name__},
                )
        if refs:
            binding = digest(sorted(refs))
            previous = store.get(experiment_id, "weave_leaderboard", "current")
            if not previous or previous.get("content_hash") != binding or not previous.get("remote_ref"):
                try:
                    ref = self.publish_leaderboard(sorted(refs))
                    store.put(
                        experiment_id,
                        "weave_leaderboard",
                        "current",
                        {"content_hash": binding, "remote_ref": ref},
                    )
                except Exception as exc:  # noqa: BLE001 - optional publication remains pending
                    store.put(
                        experiment_id,
                        "weave_leaderboard",
                        "current",
                        {"content_hash": binding, "status": "pending", "error": type(exc).__name__},
                    )
        return result


def sanitize_trace(value: Any) -> Any:
    """Drop engine objects and credential fields before the SDK serializes them."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            key: sanitize_trace(item)
            for key, item in value.items()
            if key not in {"self", "gateway", "config", "client"}
            and (
                key != "messages"
                or os.getenv("HERD_TRACE_CONVERSATIONS", "0").lower() in {"1", "true", "yes"}
            )
            and not any(
                token in key.lower()
                for token in ("api_key", "authorization", "password", "secret", "control_token")
            )
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_trace(item) for item in value]
    if isinstance(value, str):
        for key, secret in os.environ.items():
            if len(secret) >= 8 and any(
                token in key.upper() for token in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
            ):
                value = value.replace(secret, "[REDACTED]")
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return "[runtime object omitted]"


def traced(name: str):
    """Optional operation instrumentation; initialization remains an explicit operator action."""
    try:
        import weave

        return weave.op(name=name, postprocess_inputs=sanitize_trace, postprocess_output=sanitize_trace)
    except ImportError:
        return lambda function: function


async def log_execution_pair(name: str, attempts: list[AttemptRecord], metadata: dict | None = None):
    """Log just-completed actual worker rows during execution; never re-run a worker.

    Separate from durable recorded-oracle replay. Optional telemetry failure cannot
    alter admission. Local evidence remains authoritative and recoverable.
    """
    if not attempts or any(a.mode != "measured" for a in attempts):
        return {"status": "excluded"}
    try:
        import weave
        from weave.trace.context.weave_client_context import get_weave_client

        if get_weave_client() is None:
            return {"status": "unconfigured"}
        logger = weave.EvaluationLogger(
            name=name,
            model={"name": "HERD live workers", "execution_mode": "actual_worker_execution"},
            eval_attributes=sanitize_trace(metadata or {}),
        )
        for attempt in attempts:
            with logger.log_prediction(
                inputs={
                    "task_id": attempt.task_id,
                    "arm": attempt.arm,
                    "pool_hash": attempt.pool_hash,
                    "run_id": attempt.run_id,
                },
                output=sanitize_trace(attempt.model_dump(mode="json")),
                example_id=attempt.run_id,
            ) as row:
                row.log_score("behavior", behavioral_scores(attempt.model_dump(mode="json")))
        logger.log_summary()
        return {"status": "logged", "mode": "actual_worker_execution"}
    except Exception as exc:  # noqa: BLE001 - telemetry must not alter worker outcomes
        import logging

        logging.getLogger(__name__).warning("Live evaluation pending: %s", type(exc).__name__)
        return {"status": "unavailable", "error_type": type(exc).__name__}

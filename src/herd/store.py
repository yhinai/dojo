"""Durable local state; every mutation appends a tamper-evident event."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

from herd.schemas import RunEvent, digest, utcnow


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""PRAGMA journal_mode=WAL; PRAGMA busy_timeout=10000;
        CREATE TABLE IF NOT EXISTS objects(experiment TEXT,kind TEXT,id TEXT,payload TEXT,PRIMARY KEY(experiment,kind,id));
        CREATE TABLE IF NOT EXISTS events(experiment TEXT,sequence INTEGER,payload TEXT,PRIMARY KEY(experiment,sequence));
        """)

    def get(self, experiment, kind, key, default=None):
        with self.lock:
            row = self.db.execute(
                "SELECT payload FROM objects WHERE experiment=? AND kind=? AND id=?", (experiment, kind, key)
            ).fetchone()
        return json.loads(row[0]) if row else default

    def list(self, experiment, kind):
        with self.lock:
            rows = self.db.execute(
                "SELECT payload FROM objects WHERE experiment=? AND kind=? ORDER BY rowid", (experiment, kind)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def page(self, experiment, kind, limit=100, offset=0):
        with self.lock:
            rows = self.db.execute(
                "SELECT payload FROM objects WHERE experiment=? AND kind=? ORDER BY rowid LIMIT ? OFFSET ?",
                (experiment, kind, limit, offset),
            ).fetchall()
            total = self.db.execute(
                "SELECT count(*) FROM objects WHERE experiment=? AND kind=?", (experiment, kind)
            ).fetchone()[0]
        return {
            "items": [json.loads(r[0]) for r in rows],
            "total": total,
            "next_offset": offset + len(rows) if offset + len(rows) < total else None,
        }

    def event_page(self, experiment, after=0, limit=100):
        with self.lock:
            rows = self.db.execute(
                "SELECT payload FROM events WHERE experiment=? AND sequence>? ORDER BY sequence LIMIT ?",
                (experiment, after, limit),
            ).fetchall()
        items = [json.loads(r[0]) for r in rows]
        return {"items": items, "next_after": items[-1]["sequence"] if items else after}

    def reconcile_abandoned(self):
        """Only alter running records while holding the global scheduler lease.

        An external CLI scheduler holds this same lease, so API startup cannot
        misclassify its active experiment as abandoned.
        """
        recovered = []
        try:
            with self.execution_lock():
                for exp in self.experiments():
                    if exp.get("status") == "running":
                        self.put(
                            exp["id"],
                            "experiment",
                            exp["id"],
                            {**exp, "status": "paused", "pause_reason": "scheduler_process_lost"},
                            expected=exp,
                        )
                        self.event(
                            exp["id"],
                            "recovery.abandoned_scheduler",
                            {"action": "paused", "reservations": "preserved"},
                        )
                        recovered.append(exp["id"])
        except RuntimeError:
            pass
        return recovered

    def experiments(self, limit=None, offset=0):
        with self.lock:
            return [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT payload FROM objects WHERE kind='experiment' ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (-1 if limit is None else limit, offset),
                )
            ]

    def put(self, experiment, kind, key, value, *, expected=None):
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                if expected is not None and self.get(experiment, kind, key) != expected:
                    raise ValueError("Concurrent state change; reload before committing")
                self.db.execute(
                    "INSERT INTO objects VALUES(?,?,?,?) ON CONFLICT(experiment,kind,id) DO UPDATE SET payload=excluded.payload",
                    (experiment, kind, key, json.dumps(value)),
                )
                self._event(experiment, f"{kind}.saved", {"id": key, "content_hash": digest(value)})
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        return value

    def _event(self, experiment, event_type, payload):
        row = self.db.execute(
            "SELECT sequence,payload FROM events WHERE experiment=? ORDER BY sequence DESC LIMIT 1",
            (experiment,),
        ).fetchone()
        seq = row[0] + 1 if row else 1
        prev = json.loads(row[1])["event_hash"] if row else "0" * 64
        body = {
            "event_id": uuid4().hex,
            "experiment_id": experiment,
            "sequence": seq,
            "event_type": event_type,
            "payload": payload,
            "observed_at": utcnow(),
            "previous_hash": prev,
        }
        event = RunEvent(**body, event_hash=digest(body))
        self.db.execute("INSERT INTO events VALUES(?,?,?)", (experiment, seq, event.model_dump_json()))
        return event

    def event(self, experiment, event_type, payload):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                event = self._event(experiment, event_type, payload)
                self.db.execute("COMMIT")
                return event
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def events(self, experiment):
        with self.lock:
            return [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT payload FROM events WHERE experiment=? ORDER BY sequence", (experiment,)
                )
            ]

    def verify_events(self, experiment):
        prev = "0" * 64
        for seq, event in enumerate(self.events(experiment), 1):
            body = {k: v for k, v in event.items() if k != "event_hash"}
            if (
                event["sequence"] != seq
                or event["previous_hash"] != prev
                or digest(body) != event["event_hash"]
            ):
                return False
            prev = event["event_hash"]
        return True

    def atomic_updates(self, experiment, updates, expectations=()):
        """Commit related records and their events in one transaction, with compare-and-swap."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                for kind, key, expected in expectations:
                    if self.get(experiment, kind, key) != expected:
                        raise ValueError("Concurrent state change; reload before committing")
                for kind, key, value in updates:
                    if hasattr(value, "model_dump"):
                        value = value.model_dump(mode="json")
                    self.db.execute(
                        "INSERT INTO objects VALUES(?,?,?,?) ON CONFLICT(experiment,kind,id) DO UPDATE SET payload=excluded.payload",
                        (experiment, kind, key, json.dumps(value)),
                    )
                    self._event(experiment, f"{kind}.saved", {"id": key, "content_hash": digest(value)})
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def allocate_slot(self, experiment, key, max_slots=15):
        if max_slots < 1:
            raise ValueError("Positive slot count required")
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                existing = self.get(experiment, "slot", key)
                if existing is not None:
                    slot = existing["slot"]
                else:
                    used = {s["slot"] for s in self.list(experiment, "slot")}
                    slot = next((i for i in range(max_slots) if i not in used), None)
                    if slot is None:
                        raise ValueError("Registered candidate slots exhausted")
                    self.db.execute(
                        "INSERT INTO objects VALUES(?,?,?,?)",
                        (experiment, "slot", key, json.dumps({"slot": slot, "key": key})),
                    )
                    self._event(experiment, "slot.allocated", {"key": key, "slot": slot})
                self.db.execute("COMMIT")
                return slot
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def control(self, experiment):
        return self.get(experiment, "control", "current", {"action": "resume"})

    def request_control(self, experiment, action, actor="operator"):
        if action not in {"pause", "cancel", "resume"}:
            raise ValueError("Unknown control action")
        if not actor.strip():
            raise ValueError("Operator identity required")
        exp = self.get(experiment, "experiment", experiment)
        if exp is None:
            raise ValueError("Unknown experiment")
        if exp.get("status") in {"complete", "cancelled"}:
            raise ValueError("Terminal experiment cannot be resumed or changed")
        previous = self.get(experiment, "control", "current")
        if previous and previous.get("action") == "cancel":
            raise ValueError("Cancellation is terminal")
        command = {"action": action, "actor": actor, "requested_at": utcnow()}
        self.atomic_updates(
            experiment,
            [("control", "current", command)],
            [("control", "current", previous), ("experiment", experiment, exp)],
        )
        return command

    def health(self):
        with self.lock:
            integrity = self.db.execute("PRAGMA quick_check").fetchone()[0]
        return {"database": "ok" if integrity == "ok" else "corrupt"}

    def backup(self, destination):
        destination = Path(destination)
        if destination.resolve() == self.path.resolve() or destination.exists():
            raise ValueError("Backup destination must be a new file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, sqlite3.connect(destination) as target:
            self.db.backup(target)
        return destination

    def maintenance_lock(self):
        """Shared service/run guard; full-state backups take the exclusive counterpart."""
        import fcntl
        from contextlib import contextmanager

        @contextmanager
        def locked():
            with (self.path.parent / "maintenance.lock").open("a+") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError("State maintenance is active") from None
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        return locked()

    def execution_lock(self):
        """Nonblocking OS lock: one scheduler per state root; released on process death."""
        import fcntl
        from contextlib import contextmanager

        @contextmanager
        def locked():
            lockfile = self.path.parent / "scheduler.lock"
            with self.maintenance_lock(), lockfile.open("a+") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError("Another scheduler is active in this state directory") from None
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        return locked()

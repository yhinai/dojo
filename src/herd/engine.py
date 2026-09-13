"""Resumable five-learner experiment with round barriers and immutable evaluation arms."""

from __future__ import annotations

import asyncio
import fcntl
import json
from pathlib import Path
from uuid import uuid4

from herd.config import ROOT, configuration
from herd.curator import RETRIEVER_HASH, curate, make_pool, retrieve, review_draft, semantic_review, tokens
from herd.curriculum import assigned_track, freeze_round
from herd.gateway import GatewayError, GlobalBudgetExceeded
from herd.integrations.weave import traced
from herd.lifecycle import apply_pending
from herd.pace import update_gate
from herd.schemas import (
    AttemptRecord,
    GateState,
    LessonRevision,
    LessonStatus,
    PairOutcome,
    Partition,
    PoolSnapshot,
    TrialBinding,
    digest,
    utcnow,
)
from herd.store import Store


class PairedInfrastructureError(GatewayError):
    def __init__(self, results):
        self.results = results
        super().__init__("Paired runtime failed twice; evidence retained and experiment paused")


class RunInterrupted(Exception):
    def __init__(self, action):
        self.action = action
        super().__init__(action)


async def safe_gather(*coroutines):
    tasks = [asyncio.create_task(c) for c in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except RunInterrupted:
        # Finish already allocated units, but queued attempts fail their own checkpoint.
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class Engine:
    def __init__(self, store: Store, registry, learner, root: Path, model_hash: str, concurrency=10):
        self.store = store
        self.registry = registry
        self.learner = learner
        self.root = root
        self.model_hash = model_hash
        self.semaphore = asyncio.Semaphore(concurrency)
        self.config = configuration()

    def checkpoint(self, eid):
        action = self.store.control(eid).get("action", "resume")
        if action in ("pause", "cancel"):
            raise RunInterrupted(action)

    async def auxiliary(self, eid, callback, *args):
        """Controller model calls share the same resource ceiling as task workers."""
        self.checkpoint(eid)
        async with self.semaphore:
            self.checkpoint(eid)
            return await callback(*args)

    def create(self, experiment_id=None):
        eid = experiment_id or uuid4().hex[:12]
        if self.store.get(eid, "experiment", eid):
            raise ValueError("Experiment already exists")
        pool = make_pool(eid, 0, [])
        cfg = {
            **self.config,
            "model_hash": self.model_hash,
            "curated_docs": (ROOT / "docs/snapshots/curated-marimo.md").read_text(),
        }
        exp = {
            "id": eid,
            "status": "ready",
            "phase": "development",
            "round_id": 0,
            "config": cfg,
            "created_at": utcnow(),
            "pool_hash": pool.pool_hash,
        }
        self.store.put(eid, "experiment", eid, exp)
        self.store.put(eid, "pool", pool.pool_hash, pool)
        self.store.put(eid, "head", "current", {"pool_hash": pool.pool_hash})
        return exp

    def pool(self, eid):
        return PoolSnapshot.model_validate(
            self.store.get(eid, "pool", self.store.get(eid, "head", "current")["pool_hash"])
        )

    def task(self, eid, partition, seed, track=None):
        task = self.registry.generate(partition, seed, track)
        self.store.put(eid, "task", task.task_id, task)
        return task

    @staticmethod
    def runtime_failure(record):
        return bool(
            record.status == "infrastructure_error"
            and record.result
            and record.result.infrastructure_error
            and record.infrastructure_kind in (None, "runtime")
        )

    async def attempt(
        self, eid, task, identity, round_id, pool, arm="admitted_pool", candidate=None, memory=None, key=None
    ):
        result = await self._attempt_once(eid, task, identity, round_id, pool, arm, candidate, memory, key)
        if self.runtime_failure(result) and task.partition not in (Partition.ADMISSION, Partition.REGRESSION):
            # The retry is a separate session and artifact, permanently bound to the original logical unit.
            epoch = self.store.get(eid, "experiment", eid, {}).get("execution_epoch", 0)
            prior = self.store.get(eid, "runtime_retry", result.run_id, {})
            generation = prior.get("generation", 0)
            if prior.get("exhausted") and prior.get("execution_epoch") != epoch:
                generation += 1
            retry_id = digest([result.run_id, "runtime-retry-v1", generation])[:24]
            retry_state = {
                "original_run_id": result.run_id,
                "retry_run_id": retry_id,
                "limit": 1,
                "generation": generation,
                "execution_epoch": epoch,
                "exhausted": False,
            }
            self.store.put(eid, "runtime_retry", result.run_id, retry_state)
            retry = await self._attempt_once(
                eid, task, identity + ":runtime-retry", round_id, pool, arm, candidate, memory, retry_id
            )
            retry.logical_run_id = result.run_id
            retry.logical_learner_id = identity
            retry.retry_of = result.run_id
            self.store.put(eid, "attempt", retry.run_id, retry)
            if self.runtime_failure(retry):
                retry_state["exhausted"] = True
                self.store.put(eid, "runtime_retry", result.run_id, retry_state)
                raise GatewayError("Runtime failed twice; automatic retry exhausted; evidence retained")
            return retry
        return result

    @traced("attempt_task")
    async def _attempt_once(
        self, eid, task, identity, round_id, pool, arm="admitted_pool", candidate=None, memory=None, key=None
    ):
        self.checkpoint(eid)
        run_id = (
            key
            or digest(
                [
                    eid,
                    task.task_id,
                    identity,
                    round_id,
                    pool.pool_hash,
                    arm,
                    candidate.content_hash if candidate else None,
                ]
            )[:24]
        )
        existing = self.store.get(eid, "attempt", run_id)
        if existing and existing["status"] not in (
            "allocated",
            "running",
            "dollar_cap_reached",
        ):
            cached = AttemptRecord.model_validate(existing)
            if cached.status == "infrastructure_error" and not self.runtime_failure(cached):
                # Resume may replay the same request IDs after explicit billing reconciliation.
                pass
            else:
                return cached
        if memory is None:
            memory, ids = retrieve(
                pool,
                task.public_skill_tags,
                task.runtime_lock_hash,
                candidate=candidate,
                excluded_origins=task.origin_exclusions,
            )
        else:
            ids = []
        async with self.semaphore:
            self.checkpoint(eid)
            self.store.put(
                eid,
                "attempt",
                run_id,
                AttemptRecord(
                    run_id=run_id,
                    task_id=task.task_id,
                    learner_id=identity,
                    round_id=round_id,
                    pool_hash=pool.pool_hash,
                    arm=arm,
                    status="running",
                ),
            )
            result = await self.learner.attempt(task, run_id, identity, round_id, pool.pool_hash, memory, arm)
            result.retrieved_lesson_ids = ids
            self.store.put(eid, "attempt", run_id, result)
            if result.status == "dollar_cap_reached":
                raise GlobalBudgetExceeded("Inference cap reached; raise cap to resume cached requests")
            if result.status == "infrastructure_error" and not self.runtime_failure(result):
                raise GatewayError("Provider or runtime preflight unavailable; no automatic billed retry")
            return result

    @traced("evaluate_pair")
    async def evaluate_pair(self, eid, task, identity, round_id, pool, candidate, treatment_pool=None):
        pair_key = digest(
            [
                task.task_id,
                identity,
                round_id,
                pool.pool_hash,
                (treatment_pool or pool).pool_hash,
                candidate.content_hash if candidate else None,
            ]
        )[:24]
        for generation in range(2):
            session = identity if generation == 0 else identity + ":pair-runtime-retry"
            invocation_started = utcnow()
            results = await safe_gather(
                self.attempt(eid, task, session, round_id, pool, "control"),
                self.attempt(eid, task, session, round_id, treatment_pool or pool, "treatment", candidate),
            )
            if not any(self.runtime_failure(x) for x in results):
                from herd.integrations.weave import log_execution_pair

                receipt_key = f"{pair_key}-{generation}"
                fresh = [x for x in results if x.started_at >= invocation_started]
                if fresh and not self.store.get(eid, "live_evaluation", receipt_key):
                    receipt = await log_execution_pair(
                        "paired_worker_execution",
                        fresh,
                        {
                            "pair_key": pair_key,
                            "generation": generation,
                            "experiment_id": eid,
                            "partition": task.partition.value,
                            "all_pair_run_ids": [x.run_id for x in results],
                            "cached_run_ids": [x.run_id for x in results if x not in fresh],
                        },
                    )
                    if receipt.get("status") == "logged":
                        self.store.put(
                            eid,
                            "live_evaluation",
                            receipt_key,
                            {
                                **receipt,
                                "run_ids": [x.run_id for x in fresh],
                                "pair_key": pair_key,
                                "generation": generation,
                            },
                        )
                return results
            self.store.put(
                eid,
                "pair_retry",
                f"{pair_key}-{generation}",
                {
                    "pair_key": pair_key,
                    "generation": generation,
                    "task_id": task.task_id,
                    "run_ids": [x.run_id for x in results],
                    "valid": False,
                    "reason": "Runtime infrastructure failure",
                    "counts_as_evidence": False,
                },
            )
        raise PairedInfrastructureError(results)

    async def controls(self, eid, round_id, pool, candidate=None, namespace=0, treatment_pool=None):
        """Paired regression sentinel tasks: candidate may not break a control success."""
        for track in range(5):
            task = self.task(eid, Partition.REGRESSION, round_id * 10000 + namespace * 100 + track, track)
            recovery_key = digest(
                [
                    round_id,
                    namespace,
                    track,
                    pool.pool_hash,
                    candidate.content_hash if candidate else None,
                    treatment_pool.pool_hash if treatment_pool else None,
                ]
            )[:24]
            recovery = self.store.get(eid, "control_recovery", recovery_key, {"generation": 0})
            identity = (
                "regression" if recovery["generation"] == 0 else f"regression:resume-{recovery['generation']}"
            )
            try:
                a, b = await self.evaluate_pair(
                    eid, task, identity, round_id, pool, candidate, treatment_pool=treatment_pool
                )
            except PairedInfrastructureError:
                self.store.put(
                    eid,
                    "control_recovery",
                    recovery_key,
                    {"generation": recovery["generation"] + 1, "pending_operator_resume": True},
                )
                raise
            if not a.result or not b.result or a.result.infrastructure_error or b.result.infrastructure_error:
                raise GatewayError(
                    "Regression infrastructure unavailable; candidate decision remains pending"
                )
            if a.result.success and not b.result.success:
                return False
            if any(
                not x.result.checks
                or not any(c.name == "integrity" and c.passed for c in x.result.checks)
                or any(c.name == "integrity" and not c.passed for c in x.result.checks)
                for x in (a, b)
            ):
                return False
        return True

    @traced("decide_admission")
    async def gate(self, eid, round_id, pool, candidate, slot, diagnostic=False):
        binding = TrialBinding(
            candidate_hash=candidate.content_hash,
            incumbent_pool_hash=pool.pool_hash,
            retriever_hash=RETRIEVER_HASH,
            model_config_hash=self.model_hash,
            runtime_lock_hash=self.config["runtime_hash"],
            docs_snapshot_hash=self.config["docs_hash"],
            sampler_hash=digest(
                [
                    "admission-v2",
                    slot,
                    "diagnostic" if diagnostic else "primary",
                    sorted(candidate.origin_task_ids),
                ]
            ),
        )
        trial_id = digest([eid, slot, binding.binding_hash, diagnostic])[:24]
        gate_kind = "control_gate" if diagnostic else "gate"
        if not diagnostic:
            reservation = {"trial_id": trial_id, "binding_hash": binding.binding_hash, "slot_id": slot}
            old_slot = self.store.get(eid, "gate_slot", str(slot))
            if old_slot and old_slot != reservation:
                raise ValueError("Candidate slot already bound to another immutable trial")
            self.store.put(eid, "gate_slot", str(slot), reservation)
        old = self.store.get(eid, gate_kind, trial_id)
        state = (
            GateState.model_validate(old)
            if old
            else GateState(trial_id=trial_id, slot_id=slot, binding=binding)
        )
        candidate.trial_id = trial_id
        if state.controls_passed is None:
            state.controls_passed = await self.controls(eid, round_id, pool, candidate, slot + 1)
            if not state.controls_passed:
                state.decision = "rejected"
                state.reason = "Regression or integrity control failed"
            self.store.put(eid, gate_kind, trial_id, state)
        while state.decision == "evaluating":
            index = len(state.pair_ids)
            self.checkpoint(eid)
            seed = (1000000 if diagnostic else 0) + slot * 1000 + index
            task = self.task(eid, Partition.ADMISSION, seed)
            if task.task_id in candidate.origin_task_ids or task.partition != Partition.ADMISSION:
                raise ValueError("Sampler violated development/admission separation")
            if task.task_id in state.task_ids:
                raise ValueError("Sampler repeated an admission task")
            infrastructure_failure = None
            try:
                a, b = await self.evaluate_pair(eid, task, f"pair-{slot}-{index}", round_id, pool, candidate)
            except PairedInfrastructureError as exc:
                a, b = exc.results
                infrastructure_failure = exc
            valid = all(
                x.status not in ("infrastructure_error", "dollar_cap_reached")
                and not (x.result and x.result.infrastructure_error)
                for x in (a, b)
            )
            pair = PairOutcome(
                pair_id=f"{trial_id}-{index}",
                task_id=task.task_id,
                binding_hash=binding.binding_hash,
                control_run_id=a.run_id,
                treatment_run_id=b.run_id,
                control_success=bool(a.result and a.result.success),
                treatment_success=bool(b.result and b.result.success),
                valid=valid,
                invalid_reason=None if valid else "Infrastructure failure",
            )
            state = update_gate(state, pair)
            self.store.atomic_updates(
                eid,
                [
                    ("control_pair" if diagnostic else "pair", pair.pair_id, pair),
                    (gate_kind, trial_id, state),
                ],
            )
            if infrastructure_failure:
                # Consume this draw once, preserve its invalidity, and pause. Resume draws a new task.
                raise infrastructure_failure
        self.store.event(
            eid,
            "control.admission_decision",
            {
                "trial_id": trial_id,
                "controls_passed": state.controls_passed,
                "decision": state.decision,
                "reason": state.reason,
            },
        )
        candidate.status = LessonStatus(state.decision)
        candidate.paired_helpful = state.wins
        candidate.paired_harmful = state.losses
        candidate.paired_ties = state.ties
        candidate.decision_reason = state.reason
        if not diagnostic:
            self.store.put(eid, "lesson_history", digest(candidate), candidate)
            self.store.put(eid, "lesson", candidate.lesson_id, candidate)
        return candidate

    async def run_false_controls(self, eid):
        """Diagnostic stream never uses primary slots or writes lessons/pool."""
        from herd.controls import false_drafts

        pool = self.pool(eid)
        records = []
        for index, draft in enumerate(false_drafts(self.config["runtime_hash"])):
            key = digest([draft.content_hash, pool.pool_hash])[:24]
            prior = self.store.get(eid, "poisoning_control", key)
            if prior and prior.get("complete"):
                records.append(prior)
                continue
            review = review_draft(draft, pool.lessons)
            record = {
                "id": key,
                "draft": draft.model_dump(mode="json"),
                "findings": review,
                "pool_hash": pool.pool_hash,
                "injected": True,
                "published": False,
                "stream": "diagnostic_not_primary_alpha",
                "complete": False,
            }
            self.store.put(eid, "poisoning_control", key, record)
            if review:
                record.update(decision="rejected", stage="curator", complete=True)
            else:
                candidate = curate(draft, pool.lessons)
                result = await self.gate(eid, 3, pool, candidate, index, diagnostic=True)
                record.update(
                    decision=result.status.value,
                    stage="behavioral_gate",
                    complete=True,
                    trial_id=result.trial_id,
                    reason=result.decision_reason,
                    safeguard_passed=result.status != LessonStatus.ADMITTED,
                )
            records.append(record)
            self.store.put(eid, "poisoning_control", key, record)
        return records

    async def develop(self, eid, round_id, pool, learner_index):
        candidate_key = f"{round_id}-{learner_index}"
        saved = self.store.get(eid, "candidate_slot", candidate_key)
        if saved is not None:
            return LessonRevision.model_validate(saved["candidate"]) if saved["candidate"] else None
        candidate = None
        curriculum = freeze_round(self.store, eid, round_id)
        for n in range(3):
            task = self.task(
                eid,
                Partition.DEVELOPMENT,
                round_id * 1000 + learner_index * 10 + n,
                assigned_track(curriculum, learner_index, n),
            )
            attempt = await self.attempt(eid, task, f"learner-{learner_index + 1}", round_id, pool)
            if (
                candidate is None
                and attempt.result
                and attempt.result.success
                and not attempt.first_submission_success
                and attempt.submissions > 1
            ):
                draft = await self.auxiliary(eid, self.learner.distill, attempt, task)
                if draft:
                    if not self.store.get(eid, "raw_slot", candidate_key):
                        self.store.put(
                            eid,
                            "raw_slot",
                            candidate_key,
                            {
                                "round_id": round_id,
                                "learner_index": learner_index,
                                "draft": draft.model_dump(mode="json"),
                            },
                        )
                    review = {
                        "draft": draft.model_dump(mode="json"),
                        "run_id": attempt.run_id,
                        "findings": review_draft(draft, pool.lessons, [task]),
                        "created_at": utcnow(),
                    }
                    if (
                        draft.runtime_lock_hash != task.runtime_lock_hash
                        or draft.tool != "marimo"
                        or draft.origin_task_ids != [task.task_id]
                        or draft.repair_run_ids != [attempt.run_id]
                        or draft.origin_learner_id != attempt.learner_id
                        or draft.origin_round != round_id
                    ):
                        review["findings"].append(
                            {
                                "code": "provenance_mismatch",
                                "detail": "Draft differs from its verified repair origin",
                            }
                        )
                    if not review["findings"]:
                        gateway = getattr(self.learner, "gateway", None)
                        if gateway is not None:
                            review["semantic"] = await self.auxiliary(
                                eid, semantic_review, gateway, draft, pool.lessons, task
                            )
                        elif attempt.mode == "measured":
                            raise ValueError("Measured candidates require configured semantic curator")
                        else:
                            review["semantic"] = {"decision": "clear", "mode": "fixture_static_only"}
                    self.store.put(eid, "draft_review", digest(review), review)
                    if review["findings"] or review.get("semantic", {}).get("decision") == "quarantine":
                        self.store.event(
                            eid,
                            "lesson.quarantined",
                            {"reason": "Semantic curator review", "draft_hash": draft.content_hash},
                        )
                        continue
                    try:
                        candidate = curate(draft, pool.lessons, [task])
                    except ValueError as exc:
                        self.store.event(
                            eid, "lesson.quarantined", {"reason": str(exc), "run_id": attempt.run_id}
                        )
        self.store.put(
            eid,
            "candidate_slot",
            candidate_key,
            {"candidate": candidate.model_dump(mode="json") if candidate else None},
        )
        if candidate:
            self.store.put(eid, "lesson", candidate.lesson_id, candidate)
        return candidate

    async def run(self, eid):
        lock_dir = self.root / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        with (lock_dir / (digest(eid) + ".lock")).open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Experiment is already running in another process") from None
            try:
                with self.store.execution_lock():
                    return await self._run_locked(eid)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    async def _run_locked(self, eid):
        exp = self.store.get(eid, "experiment", eid)
        if not exp:
            raise ValueError("Unknown experiment")
        if exp["status"] == "complete":
            return exp
        if (
            exp["config"]["protocol_hash"] != self.config["protocol_hash"]
            or exp["config"]["raw_rule_hash"] != self.config["raw_rule_hash"]
            or exp["config"]["model_hash"] != self.model_hash
            or exp["config"]["runtime_hash"] != self.config["runtime_hash"]
            or exp["config"]["docs_hash"] != self.config["docs_hash"]
            or exp["config"].get("curated_docs_hash") != self.config.get("curated_docs_hash")
        ):
            raise ValueError("Frozen experiment binding changed; create a new experiment")
        exp["status"] = "running"
        exp["execution_epoch"] = exp.get("execution_epoch", 0) + 1
        self.store.put(eid, "experiment", eid, exp)
        try:
            for round_id in range(1, 4):
                if self.store.get(eid, "round", str(round_id), {}).get("complete"):
                    continue
                checkpoint = self.store.get(eid, "round", str(round_id))
                if checkpoint and checkpoint.get("prepared_pool"):
                    current = self.pool(eid).pool_hash
                    if current == checkpoint["start_pool"]:
                        self.store.put(
                            eid,
                            "head",
                            "current",
                            {"pool_hash": checkpoint["prepared_pool"]},
                            expected={"pool_hash": current},
                        )
                    elif current != checkpoint["prepared_pool"]:
                        raise ValueError("Round commit head diverged")
                    self.store.put(
                        eid,
                        "round",
                        str(round_id),
                        {
                            "complete": True,
                            "start_pool": checkpoint["start_pool"],
                            "end_pool": checkpoint["prepared_pool"],
                        },
                    )
                    continue
                pool = (
                    PoolSnapshot.model_validate(self.store.get(eid, "pool", checkpoint["start_pool"]))
                    if checkpoint
                    else self.pool(eid)
                )
                if not checkpoint:
                    self.checkpoint(eid)
                    await apply_pending(
                        self.store,
                        eid,
                        round_id,
                        lambda old, new, selected_round=round_id: self.controls(
                            eid, selected_round, old, namespace=777, treatment_pool=new
                        ),
                    )
                    freeze_round(self.store, eid, round_id)
                    pool = self.pool(eid)
                    self.store.put(
                        eid, "round", str(round_id), {"complete": False, "start_pool": pool.pool_hash}
                    )
                exp.update(phase="development", round_id=round_id)
                self.store.put(eid, "experiment", eid, exp)
                candidates = await safe_gather(*(self.develop(eid, round_id, pool, i) for i in range(5)))
                exp["phase"] = "admission"
                self.store.put(eid, "experiment", eid, exp)
                tested = await safe_gather(
                    *(
                        self.gate(eid, round_id, pool, c, (round_id - 1) * 5 + i)
                        for i, c in enumerate(candidates)
                        if c
                    )
                )
                admitted = [c for c in tested if c.status == LessonStatus.ADMITTED]
                lessons = list(pool.lessons)
                for c in admitted:
                    findings = review_draft(c, lessons)
                    reverse_conflicts = [
                        x.lesson_id
                        for x in lessons
                        if c.lesson_id in x.conflicts_with and x.lesson_id not in c.supersedes
                    ]
                    if findings or reverse_conflicts:
                        c.status = LessonStatus.QUARANTINED
                        c.decision_reason = "Composition conflict or duplicate: " + json.dumps(
                            {"findings": findings, "reverse_conflicts": reverse_conflicts}, sort_keys=True
                        )
                        self.store.put(eid, "lesson_history", digest(c), c)
                        self.store.put(eid, "lesson", c.lesson_id, c)
                        self.store.event(
                            eid,
                            "lesson.composition_quarantined",
                            {
                                "lesson_id": c.lesson_id,
                                "trial_id": c.trial_id,
                                "reason": c.decision_reason,
                                "selection_order": "registered learner slot order",
                            },
                        )
                    else:
                        # Immutable snapshots retain prior versions; current records expose lifecycle status.
                        lessons = [x for x in lessons if x.lesson_id not in c.supersedes]
                        lessons.append(c)
                admitted = [c for c in admitted if c.status == LessonStatus.ADMITTED]
                proposed = make_pool(
                    eid, round_id, lessons, pool.pool_hash, [c.trial_id for c in admitted if c.trial_id]
                )
                if admitted and not await self.controls(
                    eid, round_id, pool, namespace=99, treatment_pool=proposed
                ):
                    for c in admitted:
                        c.status = LessonStatus.QUARANTINED
                        c.decision_reason = "Combined pool regression failed"
                        self.store.put(eid, "lesson", c.lesson_id, c)
                    proposed = make_pool(eid, round_id, pool.lessons, pool.pool_hash)
                for previous in pool.lessons:
                    replacement = next(
                        (x for x in proposed.lessons if previous.lesson_id in x.supersedes), None
                    )
                    if replacement:
                        superseded = previous.model_copy(
                            update={
                                "status": LessonStatus.SUPERSEDED,
                                "decision_reason": f"Superseded by admitted {replacement.lesson_id}",
                            }
                        )
                        self.store.put(eid, "lesson_history", digest(superseded), superseded)
                        if previous.lesson_id != replacement.lesson_id:
                            self.store.put(eid, "lesson", previous.lesson_id, superseded)
                self.store.put(eid, "pool", proposed.pool_hash, proposed)
                self.store.put(
                    eid,
                    "round",
                    str(round_id),
                    {"complete": False, "start_pool": pool.pool_hash, "prepared_pool": proposed.pool_hash},
                )
                self.store.put(
                    eid,
                    "head",
                    "current",
                    {"pool_hash": proposed.pool_hash},
                    expected={"pool_hash": pool.pool_hash},
                )
                self.store.put(
                    eid,
                    "round",
                    str(round_id),
                    {"complete": True, "start_pool": pool.pool_hash, "end_pool": proposed.pool_hash},
                )
            exp["phase"] = "negative_controls"
            self.store.put(eid, "experiment", eid, exp)
            await self.run_false_controls(eid)
            await self.final(eid)
            exp.update(status="complete", phase="complete", pool_hash=self.pool(eid).pool_hash)
        except RunInterrupted as exc:
            exp = self.store.get(eid, "experiment", eid)
            exp.update(status="cancelled" if exc.action == "cancel" else "paused", error=None)
            self.store.put(eid, "experiment", eid, exp)
            return exp
        except BaseException as exc:
            exp = self.store.get(eid, "experiment", eid)
            exp.update(status="paused", error=f"{type(exc).__name__}: {exc}")
            self.store.put(eid, "experiment", eid, exp)
            raise
        self.store.put(eid, "experiment", eid, exp)
        return exp

    async def final(self, eid):
        from herd.reports import attach_accounting, build_report, experiment_accounting

        self.checkpoint(eid)
        pool = self.pool(eid)
        exp = self.store.get(eid, "experiment", eid)
        exp["phase"] = "final"
        self.store.put(eid, "experiment", eid, exp)
        raw = []
        for slot in sorted(
            self.store.list(eid, "raw_slot"), key=lambda x: (x["round_id"], x["learner_index"])
        ):
            c = slot["draft"]
            raw.append({"instruction": c["instruction"], "scope_tags": c["scope_tags"]})
        frozen = {
            "pool_hash": pool.pool_hash,
            "curated_docs_hash": digest(exp["config"]["curated_docs"]),
            "raw_memory_hash": digest(raw),
            "model_hash": self.model_hash,
            "retriever_hash": RETRIEVER_HASH,
            "tasks_hash": digest(
                [
                    self.registry.generate(Partition.FINAL, 100000 + n).model_dump(mode="json")
                    for n in range(60)
                ]
            ),
        }
        prior = self.store.get(eid, "final_freeze", "current")
        if prior and prior != frozen:
            raise ValueError("Final evaluation is frozen")
        self.store.put(eid, "final_freeze", "current", frozen)
        jobs = []
        families = {}
        for n in range(60):
            task = self.task(eid, Partition.FINAL, 100000 + n)
            families[task.task_id] = task.family_id
            selected = []
            for c in raw:
                if (
                    set(c["scope_tags"]) & set(task.public_skill_tags)
                    and tokens(json.dumps(selected + [c])) <= 2000
                ):
                    selected.append(c)
            for repeat in range(3):
                for arm in ("no_pool", "curated_docs", "raw_memory", "admitted_pool"):
                    memory = {
                        "no_pool": "",
                        "curated_docs": exp["config"]["curated_docs"],
                        "raw_memory": json.dumps(selected),
                        "admitted_pool": None,
                    }[arm]
                    jobs.append(self.attempt(eid, task, f"final-{repeat}", 4, pool, arm, memory=memory))
        attempts = await safe_gather(*jobs)
        report = build_report(eid, pool.pool_hash, attempts, families)
        ledger = getattr(getattr(self.learner, "gateway", None), "ledger", None)
        report = attach_accounting(report, experiment_accounting(self.store, eid, ledger))
        self.store.put(eid, "report", "current", report)

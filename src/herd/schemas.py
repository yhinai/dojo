from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    data = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Partition(StrEnum):
    CALIBRATION = "calibration"
    DEVELOPMENT = "development"
    ADMISSION = "admission"
    REGRESSION = "regression"
    FINAL = "final"
    DEMONSTRATION = "demonstration"


class WorkerBudget(Model):
    max_tool_calls: int = Field(default=12, gt=0)
    max_submissions: int = Field(default=3, gt=0)
    max_total_tokens: int = Field(default=80000, gt=0)
    max_output_tokens_per_turn: int = Field(default=1500, gt=0)
    max_wall_seconds: float = Field(default=180, gt=0)
    max_memory_envelope_tokens: int = Field(default=2000, gt=0)


class TaskManifest(Model):
    task_id: str
    template_id: str
    family_id: str
    track: int = Field(ge=0, le=4)
    partition: Partition
    public_request: str
    public_fixture: dict[str, Any] = Field(default_factory=dict)
    public_skill_tags: list[str] = Field(default_factory=list)
    runtime_lock_hash: str
    docs_snapshot_hash: str
    oracle_version: str = "herd-oracle-v1"
    budget: WorkerBudget = Field(default_factory=WorkerBudget)
    origin_exclusions: list[str] = Field(default_factory=list)
    assignment_seed: int = 0

    def public_context(self) -> dict[str, Any]:
        return {
            "request": self.public_request,
            "fixture": self.public_fixture,
            "skill_tags": self.public_skill_tags,
            "runtime": self.runtime_lock_hash,
        }


class CheckResult(Model):
    name: str
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class BehaviorResult(Model):
    task_id: str
    success: bool
    checks: list[CheckResult]
    infrastructure_error: str | None = None
    artifact_hash: str = ""
    duration_ms: float = 0
    evidence_paths: list[str] = Field(default_factory=list)
    mode: str = "measured"

    @model_validator(mode="after")
    def truthful_success(self):
        if self.success and (
            not self.checks or not all(c.passed for c in self.checks) or self.infrastructure_error
        ):
            raise ValueError("success requires nonempty passing checks and no infrastructure error")
        return self


class AttemptRecord(Model):
    run_id: str
    task_id: str
    learner_id: str
    round_id: int
    pool_hash: str
    arm: str = "admitted_pool"
    status: Literal[
        "allocated",
        "running",
        "completed",
        "budget_exhausted",
        "dollar_cap_reached",
        "infrastructure_error",
        "cancelled",
    ] = "allocated"
    source: str = ""
    initial_source: str = ""
    result: BehaviorResult | None = None
    first_submission_success: bool = False
    submissions: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    retrieved_lesson_ids: list[str] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    workspace: str = ""
    started_at: str = Field(default_factory=utcnow)
    completed_at: str | None = None
    mode: str = "measured"


class LessonStatus(StrEnum):
    QUARANTINED = "quarantined"
    EVALUATING = "evaluating"
    ADMITTED = "admitted"
    REJECTED = "rejected"
    INSUFFICIENT = "insufficient_evidence"
    RETRACTED = "retracted"
    SUPERSEDED = "superseded"


class LessonDraft(Model):
    lesson_id: str
    revision: int = Field(default=1, ge=1)
    tool: str = "marimo"
    runtime_lock_hash: str
    scope_tags: list[str] = Field(min_length=1)
    trigger: str = Field(min_length=5, max_length=1000)
    instruction: str = Field(min_length=10, max_length=6000)
    does_not_apply: str = Field(min_length=5, max_length=1000)
    origin_learner_id: str
    origin_round: int = Field(ge=1, le=3)
    origin_task_ids: list[str] = Field(min_length=1)
    repair_run_ids: list[str] = Field(min_length=1)
    generic_example: str = Field(default="", max_length=2000)
    conflicts_with: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)

    @property
    def content_hash(self) -> str:
        return digest(self.model_dump(mode="json"))


class LessonRevision(LessonDraft):
    status: LessonStatus = LessonStatus.QUARANTINED
    trial_id: str | None = None
    retrieved: int = 0
    paired_helpful: int = 0
    paired_harmful: int = 0
    paired_ties: int = 0
    decision_reason: str = ""

    @property
    def content_hash(self) -> str:
        return digest({k: getattr(self, k) for k in LessonDraft.model_fields})


class PoolSnapshot(Model):
    pool_hash: str
    parent_hash: str | None = None
    experiment_id: str
    round_id: int
    lessons: list[LessonRevision] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow)
    evidence_ids: list[str] = Field(default_factory=list)


class TrialBinding(Model):
    candidate_hash: str
    incumbent_pool_hash: str
    retriever_hash: str
    model_config_hash: str
    runtime_lock_hash: str
    docs_snapshot_hash: str
    sampler_hash: str

    @property
    def binding_hash(self) -> str:
        return digest(self)


class PairOutcome(Model):
    pair_id: str
    task_id: str
    binding_hash: str
    control_run_id: str
    treatment_run_id: str
    control_success: bool
    treatment_success: bool
    valid: bool = True
    invalid_reason: str | None = None

    @model_validator(mode="after")
    def independent_arms(self):
        if self.control_run_id == self.treatment_run_id:
            raise ValueError("Control and treatment must use distinct fresh worker runs")
        if not self.valid and not self.invalid_reason:
            raise ValueError("Invalid pairs require an explicit reason")
        return self

    @property
    def outcome(self) -> str:
        if not self.valid:
            return "invalid"
        if self.control_success == self.treatment_success:
            return "tie"
        return "win" if self.treatment_success else "loss"


class GateState(Model):
    trial_id: str
    slot_id: int = Field(ge=0, le=14)
    binding: TrialBinding
    alpha: float = Field(default=0.05, gt=0, lt=1)
    bet: float = Field(default=0.5, gt=0, lt=1)
    max_pairs: int = Field(default=64, gt=0)
    log_e: float = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    invalid: int = 0
    pair_ids: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    decision: Literal["evaluating", "admitted", "rejected", "insufficient_evidence", "quarantined"] = (
        "evaluating"
    )
    controls_passed: bool | None = None
    reason: str = ""


class RunEvent(Model):
    event_id: str
    experiment_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    observed_at: str = Field(default_factory=utcnow)
    previous_hash: str
    event_hash: str


class ExperimentReport(Model):
    experiment_id: str
    status: str
    pool_hash: str
    arms: dict[str, Any] = Field(default_factory=dict)
    comparisons: dict[str, Any] = Field(default_factory=dict)
    total_cost_usd: float = 0
    limitations: list[str] = Field(default_factory=list)
    mode: str = "measured"
    created_at: str = Field(default_factory=utcnow)

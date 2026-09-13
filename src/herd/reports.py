"""Deterministic, family-clustered summaries of frozen fresh-worker results."""

import random
import re
from collections import defaultdict
from datetime import datetime
from statistics import mean

from herd.schemas import AttemptRecord, ExperimentReport

ARMS = ("no_pool", "curated_docs", "raw_memory", "admitted_pool")


def build_report(
    experiment_id: str,
    pool_hash: str,
    attempts: list[AttemptRecord],
    family_by_task: dict[str, str],
    status: str = "complete",
) -> ExperimentReport:
    if len({a.run_id for a in attempts}) != len(attempts):
        raise ValueError("duplicate worker run IDs")
    if any(a.task_id not in family_by_task for a in attempts):
        raise ValueError("every task requires a declared family")
    modes = {a.mode for a in attempts}
    if len(modes) > 1:
        raise ValueError("cannot mix fixture and measured attempts")
    report = ExperimentReport(
        experiment_id=experiment_id, pool_hash=pool_hash, status=status, mode=next(iter(modes), "measured")
    )
    report.limitations = [
        "Intervals resample task families, not individual episodes; descriptive for this task set.",
        "One learned pool does not establish repeatability of the entire learning process.",
        "Costs cover supplied final-evaluation attempts; total learning/gating spend is reported separately by the experiment ledger.",
    ]
    valid_by_arm = {}
    for arm in ARMS:
        records = [a for a in attempts if a.arm == arm]
        valid = [
            a
            for a in records
            if (
                a.result is not None
                and not a.result.infrastructure_error
                and a.status != "infrastructure_error"
            )
            or (a.result is None and a.status in {"budget_exhausted", "timeout", "failed"})
        ]
        valid_by_arm[arm] = valid
        known = [a.cost_usd for a in records if a.cost_usd is not None]
        report.arms[arm] = {
            "allocated": len(records),
            "evaluated": len(valid),
            "infrastructure_errors": sum(bool(a.result and a.result.infrastructure_error) for a in records),
            "pending": sum(
                a.result is None and a.status not in {"budget_exhausted", "timeout", "failed"}
                for a in records
            ),
            "successes": sum(bool(a.result and a.result.success) for a in valid),
            "success_rate": mean(bool(a.result and a.result.success) for a in valid) if valid else None,
            "first_submission_rate": mean(a.first_submission_success for a in valid) if valid else None,
            "input_tokens": sum(a.input_tokens for a in records),
            "output_tokens": sum(a.output_tokens for a in records),
            "tool_calls": sum(a.tool_calls for a in records),
            "known_cost_usd": sum(known),
            "cost_complete": len(known) == len(records),
            "families": len({family_by_task[a.task_id] for a in valid}),
        }
    report.total_cost_usd = sum(a.cost_usd for a in attempts if a.cost_usd is not None)
    if any(a.cost_usd is None for a in attempts):
        report.limitations.append("Total cost is the known subtotal; some episode prices are unavailable.")
    if any(a.arm not in ARMS for a in attempts):
        report.limitations.append(
            "Non-final arms excluded from arm comparisons; their known costs remain included."
        )

    # Match repeated trials by their stable learner/repeat identity, never by success or arrival order.
    def keyed(records):
        output = {}
        for a in records:
            key = (a.task_id, a.logical_learner_id or a.learner_id)
            if key in output:
                raise ValueError("duplicate task/repeat identity within arm")
            output[key] = a
        return output

    treatment = keyed(valid_by_arm["admitted_pool"])
    for baseline in ARMS[:-1]:
        control = keyed(valid_by_arm[baseline])
        common = sorted(treatment.keys() & control.keys())
        families = defaultdict(list)
        raw = []
        for key in common:
            delta = int(bool(treatment[key].result and treatment[key].result.success)) - int(
                bool(control[key].result and control[key].result.success)
            )
            families[family_by_task[key[0]]].append(delta)
            raw.append(
                {
                    "task_id": key[0],
                    "repeat_id": key[1],
                    "family_id": family_by_task[key[0]],
                    "treatment_run_id": treatment[key].run_id,
                    "control_run_id": control[key].run_id,
                    "difference": delta,
                }
            )
        ci = None
        if len(families) >= 2:
            rng = random.Random(20260913)
            clusters = [families[k] for k in sorted(families)]
            boot = sorted(
                mean(x for group in rng.choices(clusters, k=len(clusters)) for x in group)
                for _ in range(4000)
            )
            ci = [boot[99], boot[3899]]
        report.comparisons[f"admitted_pool_minus_{baseline}"] = {
            "difference": mean(r["difference"] for r in raw) if raw else None,
            "interval_95": ci,
            "interval_unit": "task_family_cluster",
            "bootstrap_seed": 20260913,
            "bootstrap_samples": 4000,
            "matched_episodes": len(raw),
            "families": len(families),
            "unmatched_episodes": len(treatment) + len(control) - 2 * len(common),
            "paired_outcomes": raw,
        }
    if not attempts:
        report.limitations.append("No worker results recorded; there is no measured learning estimate.")
    return report


def experiment_accounting(store, experiment_id: str, ledger=None) -> dict:
    """Account once per provider request, including distillation and unresolved charges.

    Episode cost fields are only a fallback when no durable ledger is available.
    Concurrent episode durations are summed separately from elapsed experiment time.
    """
    attempts = store.list(experiment_id, "attempt")
    tasks = {t["task_id"]: t for t in store.list(experiment_id, "task")}
    by_run = {a["run_id"]: a for a in attempts}
    stages = {
        name: {
            "requests": 0,
            "known_cost_usd": 0.0,
            "unresolved_requests": 0,
            "reserved_unknown_usd": 0.0,
            "episode_seconds": 0.0,
            "episodes": 0,
        }
        for name in (
            "development",
            "repair",
            "distillation",
            "curation",
            "admission",
            "regression",
            "final",
            "demonstration",
            "calibration",
            "other",
        )
    }

    def stage_for(attempt):
        return tasks.get(attempt["task_id"], {}).get("partition", "other")

    def seconds(start, end):
        try:
            return max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
        except (ValueError, TypeError):
            return None

    for attempt in attempts:
        row = stages.setdefault(stage_for(attempt), stages["other"].copy())
        row["episodes"] += 1
        duration = seconds(attempt.get("started_at"), attempt.get("completed_at"))
        if duration is not None:
            row["episode_seconds"] += duration
    entries = ledger.entries(list(by_run)) if ledger is not None else []
    for entry in entries:
        run_id = next(
            (
                key
                for key in sorted(by_run, key=len, reverse=True)
                if entry["request_id"].startswith(key + ":")
            ),
            None,
        )
        attempt = by_run.get(run_id)
        if attempt is None:
            continue
        logical_id = re.sub(r":retry:\d+$", "", entry["request_id"])
        stage = "distillation" if logical_id.endswith(":distill") else stage_for(attempt)
        if ":curation:" in logical_id:
            stage = "curation"
        # First model response creates the initial submission. Subsequent responses
        # may inspect or repair it, so request-level classification is conservative.
        if stage == "development" and ":turn:" in logical_id:
            turn = int(logical_id.rsplit(":turn:", 1)[1])
            if turn > 0:
                stage = "repair"
        row = stages.setdefault(stage, stages["other"].copy())
        row["requests"] += 1
        if entry.get("charged") is None:
            row["unresolved_requests"] += 1
            row["reserved_unknown_usd"] += entry["reserved"]
        else:
            row["known_cost_usd"] += entry["charged"]
    if ledger is None:
        for attempt in attempts:
            row = stages.setdefault(stage_for(attempt), stages["other"].copy())
            if attempt.get("cost_usd") is not None:
                row["known_cost_usd"] += attempt["cost_usd"]
            else:
                row["unresolved_requests"] += 1
    experiment = store.get(experiment_id, "experiment", experiment_id, {})
    events = store.events(experiment_id)
    last_time = events[-1]["observed_at"] if events else experiment.get("created_at")
    unresolved = sum(row["unresolved_requests"] for row in stages.values())
    known = sum(row["known_cost_usd"] for row in stages.values())
    return {
        "source": "provider_request_ledger" if ledger is not None else "episode_subtotal",
        "stages": stages,
        "known_cost_usd": known,
        "total_cost_usd": known if ledger is not None and not unresolved else None,
        "unresolved_requests": unresolved,
        "reserved_unknown_usd": sum(row["reserved_unknown_usd"] for row in stages.values()),
        "cost_complete": ledger is not None and not unresolved,
        "elapsed_seconds": seconds(experiment.get("created_at"), last_time),
        "episode_seconds": sum(row["episode_seconds"] for row in stages.values()),
        "notes": [
            "Repair includes development model turns after the first; inspection turns may be included.",
            "Elapsed time includes pauses; summed episode time overlaps during concurrent execution.",
            "Hosting, ARIA, and unmetered external charges are excluded.",
            "Missing ledger means separate distillation costs are unavailable.",
        ],
    }


def attach_accounting(report: ExperimentReport, accounting: dict) -> ExperimentReport:
    report.comparisons["experiment_accounting"] = accounting
    report.total_cost_usd = accounting["known_cost_usd"]
    report.limitations = [line for line in report.limitations if not line.startswith("Costs cover supplied")]
    if not accounting["cost_complete"]:
        report.limitations.append(
            "Experiment cost is a known subtotal; unresolved billing is explicitly retained."
        )
    return report


def first_failure_clusters(attempts: list[dict], development_task_ids: set[str] | None = None) -> dict:
    """Round-one hook from actual first-submission oracle evidence, never final repairs."""
    groups = defaultdict(list)
    missing = 0
    for a in attempts:
        if development_task_ids is not None and a.get("task_id") not in development_task_ids:
            continue
        if a.get("round_id") != 1 or not a.get("learner_id", "").startswith("learner-"):
            continue
        initial = a.get("initial_result")
        if not initial:
            missing += 1
            continue
        if initial.get("infrastructure_error") or initial.get("success"):
            continue
        check = next((c for c in initial.get("checks", []) if not c.get("passed")), None)
        if check:
            groups[check["name"]].append(
                {
                    "run_id": a["run_id"],
                    "learner_id": a.get("logical_learner_id") or a["learner_id"].split(":", 1)[0],
                    "task_id": a["task_id"],
                    "detail": check.get("detail", ""),
                }
            )
    clusters = [
        {
            "check": key,
            "learners": sorted({r["learner_id"] for r in rows}),
            "learner_count": len({r["learner_id"] for r in rows}),
            "attempt_count": len(rows),
            "evidence": rows,
        }
        for key, rows in groups.items()
    ]
    return {
        "round_id": 1,
        "basis": "first_submission_first_failing_check",
        "clusters": sorted(clusters, key=lambda c: (-c["learner_count"], c["check"])),
        "missing_initial_evidence": missing,
        "measured_improvement_claim": False,
    }


def calibration_report(attempts, workers=4, cap_usd=25):
    records = [a.model_dump(mode="json") if hasattr(a, "model_dump") else a for a in attempts]
    # One scored outcome per logical calibration episode; costs include all retained physical sessions.
    records = list({a["run_id"]: a for a in records}.values())
    logical = {}
    for a in records:
        key = a.get("logical_run_id") or a["run_id"]
        if key not in logical or a.get("retry_of"):
            logical[key] = a
    valid = [
        a
        for a in logical.values()
        if a.get("status") != "infrastructure_error"
        and (
            (a.get("result") and not a["result"].get("infrastructure_error"))
            or (a.get("result") is None and a.get("status") in {"budget_exhausted", "timeout", "failed"})
        )
    ]
    success = mean(bool(a.get("first_submission_success")) for a in valid) if valid else None
    known = [a["cost_usd"] for a in records if a.get("cost_usd") is not None]
    durations = []
    starts, ends = [], []
    for a in records:
        try:
            start, end = datetime.fromisoformat(a["started_at"]), datetime.fromisoformat(a["completed_at"])
            durations.append(max(0, (end - start).total_seconds()))
            starts.append(start)
            ends.append(end)
        except (KeyError, ValueError, TypeError):
            pass
    from herd.controls import FALSE_LESSONS

    stages = {
        "development": 45,
        "admission": 15 * 64 * 2,
        "candidate_controls": 15 * 5 * 2,
        "composition_controls": 3 * 5 * 2,
        "false_lesson_pairs": len(FALSE_LESSONS) * 64 * 2,
        "false_lesson_controls": len(FALSE_LESSONS) * 5 * 2,
        "final": 720,
        "demonstration": 2,
    }
    n = sum(stages.values())
    cost = sum(known) / len(valid) if valid and len(known) == len(records) else None
    seconds = sum(durations) / len(valid) if valid and len(durations) == len(records) else None
    return {
        "evaluated": len(valid),
        "infrastructure_episodes": sum(
            a.get("status") == "infrastructure_error"
            or bool(a.get("result") and a["result"].get("infrastructure_error"))
            for a in records
        ),
        "physical_sessions": len(records),
        "logical_episodes": len(logical),
        "known_cost_usd": sum(known),
        "cost_complete": len(known) == len(records),
        "observed_wall_seconds": (max(ends) - min(starts)).total_seconds() if starts and ends else None,
        "first_submission_success_rate": success,
        "first_submission_failure_rate": 1 - success if success is not None else None,
        "target_failure_band": [0.3, 0.5],
        "target_is_guarantee": False,
        "too_easy_warning": success is not None and success > 0.85,
        "mean_episode_cost_usd": cost,
        "mean_episode_seconds": seconds,
        "maximum_protocol_episode_counts": stages,
        "projected_episode_cost_usd": cost * n if cost is not None else None,
        "auxiliary_cost_scenario_usd": cost * 90 if cost is not None else None,
        "total_cost_planning_scenario_usd": cost * (n + 90) if cost is not None else None,
        "projected_worker_hours": seconds * n / 3600 if seconds is not None else None,
        "ideal_parallel_hours": seconds * n / max(1, workers) / 3600 if seconds is not None else None,
        "configured_cap_usd": cap_usd,
        "extra_model_calls": {"distillation_max": 45, "semantic_curation_max": 45},
        "limitations": [
            "Projection uses measured calibration episodes, not observed complete-run spend.",
            "Auxiliary planning scenario budgets one measured mean episode cost for each of up to 45 distillations and 45 semantic reviews; this is an assumption, not measured auxiliary spend.",
            "Diagnostic/lifecycle retries can add cost. Gates may stop early; parallelism has overhead.",
            "Calibrate before training. High initial success may yield no transferable lessons.",
        ],
    }

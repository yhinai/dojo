#!/usr/bin/env python3
"""Check HERD v2 protocol defaults and reference gate arithmetic.

This does not execute a learner, notebook, sandbox, sponsor integration, or
statistical sampler. PASS is design consistency, not application verification.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def reference_update(state: dict, pair_id: str, outcome: str, binding: str,
                     bet: float) -> dict:
    """Small serializable reference for binding and duplicate-evidence checks."""
    require(binding == state["binding"], "changed stream binding")
    require(pair_id not in state["pair_ids"], "duplicate pair ID")
    require(outcome in {"win", "loss", "tie"}, "invalid outcome")
    copied = json.loads(json.dumps(state))
    copied["pair_ids"].append(pair_id)
    if outcome == "win":
        copied["log_e"] += math.log1p(bet)
    elif outcome == "loss":
        copied["log_e"] += math.log1p(-bet)
    return copied


def expect_rejected(call, expected: str) -> None:
    try:
        call()
    except ValueError as exc:
        require(expected in str(exc), f"wrong rejection: {exc}")
    else:
        raise ValueError(f"missing rejection: {expected}")


def verify(execution_ready: bool = False) -> None:
    protocol = json.loads((ROOT / "protocol.json").read_text())
    population = protocol["population"]
    admission = protocol["admission"]
    worker = protocol["worker"]
    final = protocol["final"]
    require(population["learners"] == 5, "five learners must be preserved")
    require(population["rounds"] == 3, "three rounds must be preserved")
    slots = (population["learners"] * population["rounds"]
             * population["candidates_per_learner_per_round"])
    require(slots == admission["candidate_slots"], "slot allocation mismatch")
    require(0 < admission["alpha_total"] < 1, "invalid total alpha")
    require(admission["alpha_allocation"] == "equal_reserved_slots", "unknown allocation")
    alpha_slot = admission["alpha_total"] / slots
    threshold = 1 / alpha_slot
    bet = admission["lambda"]
    require(0 < bet < 1, "invalid fixed bet")
    minimum_wins = math.ceil(math.log(threshold) / math.log1p(bet))
    require(admission["max_pairs_per_candidate"] >= minimum_wins,
            "gate cannot cross even with all wins")
    require(math.isclose(alpha_slot * slots, admission["alpha_total"]),
            "alpha allocations exceed declared family budget")
    require(admission["fresh_task_ids"], "fresh evidence required")
    require(admission["requires_regression_controls"], "regression controls required")
    require(admission["requires_integrity_controls"], "integrity controls required")
    require(admission["on_insufficient_evidence"] == "quarantine", "unsafe exhaustion rule")
    require(admission["on_duplicate_pair"] == "reject_update", "duplicate evidence allowed")
    required_binding = {
        "candidate_hash", "incumbent_pool_hash", "retriever_hash", "model_config_hash",
        "runtime_lock_hash", "docs_snapshot_hash", "sampler_hash",
    }
    require(set(admission["stream_binding_fields"]) == required_binding,
            "incomplete stream binding")
    require(worker["fresh_trial_sessions"] and worker["fresh_final_sessions"],
            "fresh worker isolation required")
    require(worker["equal_tools_and_docs_across_arms"], "unequal worker capabilities")
    require(population["round_snapshot_barrier"], "round snapshot barrier required")
    require(final["read_only_after_selection"], "final audit may not alter the pool")
    require(len(set(final["arms"])) == 4, "four unique comparison arms required")
    require(final["primary_comparison"] == ["admitted_pool", "no_pool"],
            "primary comparison changed")
    require(final["interval_unit"] == "task_family_cluster", "wrong interval unit")
    require(final["tasks"] >= final["template_families"] > 1, "invalid family coverage")

    initial = {"binding": "frozen-example", "pair_ids": [], "log_e": 0.0}
    state = initial
    for index in range(minimum_wins - 1):
        state = reference_update(state, f"pair-{index}", "win", "frozen-example", bet)
    require(state["log_e"] < math.log(threshold), "premature threshold crossing")
    resumed = json.loads(json.dumps(state))
    state = reference_update(resumed, "threshold-pair", "win", "frozen-example", bet)
    require(state["log_e"] >= math.log(threshold), "missing threshold crossing")
    tied = reference_update(state, "tie-pair", "tie", "frozen-example", bet)
    require(tied["log_e"] == state["log_e"], "tie changed evidence")
    lost = reference_update(tied, "loss-pair", "loss", "frozen-example", bet)
    require(lost["log_e"] < tied["log_e"], "loss did not reduce evidence")
    expect_rejected(lambda: reference_update(state, "threshold-pair", "win",
                                             "frozen-example", bet), "duplicate pair")
    expect_rejected(lambda: reference_update(state, "new", "win", "changed", bet),
                    "changed stream binding")
    threshold_crossed = state["log_e"] >= math.log(threshold)
    controls_pass = False
    require(not (threshold_crossed and controls_pass), "regression veto bypassed")

    for name in ["HERD.md", "ARCHITECTURE.md", "GENERALITY.md", "BUILD_PLAN.md"]:
        content = (ROOT / name).read_text()
        require(content.count("```") % 2 == 0, f"unbalanced fences in {name}")

    if execution_ready:
        required = {
            "model_id": worker["model_id"],
            "runtime_lock_hash": worker["runtime_lock_hash"],
            "docs_snapshot_hash": worker["docs_snapshot_hash"],
            "dollar_cap": protocol["resources"]["dollar_cap"],
            "verified_model_pricing": protocol["resources"]["verified_model_pricing"],
        }
        missing = [key for key, value in required.items() if value is None]
        require(not missing, "execution preflight unresolved: " + ", ".join(missing))
        raise ValueError("application execution and isolation tests still required; this checker cannot certify readiness")

    development = population["learners"] * population["rounds"] * population["development_tasks_per_learner_per_round"]
    trial = slots * admission["max_pairs_per_candidate"] * 2
    audit = final["tasks"] * len(final["arms"]) * final["worker_repeats"]
    print("HERD V2 PROTOCOL CHECK: PASS")
    print(f"Scope: {population['learners']} learners, {population['rounds']} rounds, {slots} candidate slots")
    print(f"Alpha/slot: {alpha_slot:.8f}; evidence threshold: {threshold:g}; minimum all-win pairs: {minimum_wins}")
    print(f"Worker episode ceiling before controls/retries: {development} development + {trial} admission + {audit} final = {development + trial + audit}")
    print("Checked: arithmetic, stream binding, duplicate rejection, serialized resume, ties/losses, veto, protocol flags, document fences")
    print("NOT CHECKED: application behavior, runtime isolation, valid sampling assumptions, actual transfer, sponsor integrations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-ready", action="store_true")
    args = parser.parse_args()
    try:
        verify(args.execution_ready)
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f"HERD V2 PROTOCOL CHECK: FAIL — {exc}\n")

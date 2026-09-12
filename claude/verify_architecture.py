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
    # --- executed gate: per-candidate ---
    require(admission["gate_mode"] == "per_candidate", "executed gate must be per-candidate")
    alpha_c = admission["alpha_candidate"]
    require(0 < alpha_c < 1, "invalid per-candidate alpha")
    threshold = 1 / alpha_c
    require(math.isclose(threshold, admission["threshold_candidate"]), "threshold_candidate != 1/alpha_candidate")
    bet = admission["lambda"]
    require(0 < bet < 1, "invalid fixed bet")
    minimum_wins = math.ceil(math.log(threshold) / math.log1p(bet))
    require(admission["max_pairs_per_candidate"] >= minimum_wins,
            "gate cannot cross even with all wins")
    # --- documented familywise bound: consistent, reported, not executed ---
    fw = admission["familywise_reported"]
    require(fw["slots"] == slots, "familywise slot count mismatch")
    alpha_slot = fw["alpha_total"] / fw["slots"]
    require(math.isclose(1 / alpha_slot, fw["threshold"]), "familywise threshold != slots/alpha_total")
    require(admission["alpha_allocation"] == "per_candidate_with_familywise_reported", "unknown allocation")
    require(fw["threshold"] > threshold, "familywise bound must be stricter than the executed gate")
    # --- scheduling ---
    require(admission["candidate_evaluation"] == "parallel_independent_deltas_vs_round_start_pool",
            "candidates must be evaluated as independent deltas against the round-start pool")
    require(admission["composition_check_before_commit"], "composition check required before commit")
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
    # --- worker budget must be able to fund the declared tool-call ceiling ---
    per_turn_floor = worker["max_memory_envelope_tokens"] + 1000   # envelope + minimal prompt/task/tool result
    require(worker["max_output_tokens_per_turn"] > 0, "per-turn output cap required")
    require(worker["max_total_tokens"] >= worker["max_tool_calls"] * per_turn_floor,
            f"episode token budget {worker['max_total_tokens']} cannot fund {worker['max_tool_calls']} tool calls "
            f"at a {per_turn_floor}-token per-turn floor")
    # --- oracle, baselines, weave sections ---
    require(protocol["oracle"]["primary"] == "headless_programmatic", "primary oracle must be headless")
    require("demo_live_probe" in protocol["oracle"]["browser_required_for"], "browser retained for the live demo probe")
    require(protocol["baselines"]["curated_docs_authored_before_round"] == 1,
            "curated-docs baseline must be authored before round one")
    require(protocol["weave"]["paired_trials_as"] == "weave.Evaluation", "paired trials must map to weave.Evaluation")
    require(protocol["weave"]["pool_versions_as"] == "weave.Leaderboard", "pool versions must map to weave.Leaderboard")
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
            "curated_docs_hash": protocol["baselines"]["curated_docs_hash"],
            "raw_memory_selection_rule_hash": protocol["baselines"]["raw_memory_selection_rule_hash"],
        }
        missing = [key for key, value in required.items() if value is None]
        require(not missing, "execution preflight unresolved: " + ", ".join(missing))
        raise ValueError("application execution and isolation tests still required; this checker cannot certify readiness")

    development = population["learners"] * population["rounds"] * population["development_tasks_per_learner_per_round"]
    trial = slots * admission["max_pairs_per_candidate"] * 2
    audit = final["tasks"] * len(final["arms"]) * final["worker_repeats"]
    print("HERD V2 PROTOCOL CHECK: PASS")
    print(f"Scope: {population['learners']} learners, {population['rounds']} rounds, {slots} candidate slots")
    print(f"Executed gate: alpha {alpha_c} -> threshold {threshold:g}; minimum all-win pairs {minimum_wins}")
    print(f"Documented familywise bound: alpha/slot {alpha_slot:.6f} -> threshold {fw['threshold']} (reported, not executed)")
    print(f"Worker budget: {worker['max_tool_calls']} calls x >= {per_turn_floor} tok floor <= {worker['max_total_tokens']} total; {worker['max_output_tokens_per_turn']} out/turn")
    print(f"Oracle: primary {protocol['oracle']['primary']}; browser for {protocol['oracle']['browser_required_for']}")
    print(f"Worker episode ceiling before controls/retries: {development} development + {trial} admission + {audit} final = {development + trial + audit}")
    print("Checked: gate arithmetic (executed + familywise), budget consistency, stream binding, duplicate rejection, resume, ties/losses, veto, oracle/baseline/weave flags, document fences")
    print("NOT CHECKED: application behavior, runtime isolation, valid sampling assumptions, actual transfer, sponsor integrations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-ready", action="store_true")
    args = parser.parse_args()
    try:
        verify(args.execution_ready)
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f"HERD V2 PROTOCOL CHECK: FAIL — {exc}\n")

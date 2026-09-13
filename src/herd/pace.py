"""Paired bounded e-process. Ties do not create evidence; invalid pairs consume budget."""

import math

from herd.schemas import GateState, PairOutcome


def update_gate(state: GateState, pair: PairOutcome) -> GateState:
    state = state.model_copy(deep=True)
    if state.decision != "evaluating":
        raise ValueError("Trial is closed")
    if pair.binding_hash != state.binding.binding_hash:
        raise ValueError("Trial binding changed")
    if pair.pair_id in state.pair_ids or pair.task_id in state.task_ids:
        raise ValueError("Duplicate evidence")
    if len(state.pair_ids) >= state.max_pairs:
        raise ValueError("Pair budget exhausted")
    state.pair_ids.append(pair.pair_id)
    state.task_ids.append(pair.task_id)
    outcome = pair.outcome
    if outcome == "win":
        state.wins += 1
        state.log_e += math.log1p(state.bet)
    elif outcome == "loss":
        state.losses += 1
        state.log_e += math.log1p(-state.bet)
    elif outcome == "tie":
        state.ties += 1
    else:
        state.invalid += 1
    if state.controls_passed is False:
        state.decision = "rejected"
        state.reason = "Regression or integrity control veto"
    elif state.log_e >= math.log(1 / state.alpha) and state.controls_passed is True:
        state.decision = "admitted"
        state.reason = "Per-candidate e-value crossed threshold and controls passed"
    elif len(state.pair_ids) >= state.max_pairs:
        state.decision = "insufficient_evidence"
        state.reason = "Finite pair budget exhausted without admission"
    elif state.log_e + (state.max_pairs - len(state.pair_ids)) * math.log1p(state.bet) < math.log(
        1 / state.alpha
    ):
        state.decision = "insufficient_evidence"
        state.reason = "Admission threshold unreachable within remaining pair budget"
    return state


def evidence_summary(state):
    return {
        "e_value": math.exp(state.log_e),
        "threshold": 1 / state.alpha,
        "familywise_threshold": 300,
        "familywise_crossed": state.log_e >= math.log(300),
        "decision": state.decision,
        "pairs": len(state.pair_ids),
    }

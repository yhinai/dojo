import math

import pytest

from herd.pace import evidence_summary, update_gate
from herd.schemas import GateState, PairOutcome, TrialBinding
from herd.store import Store


def binding():
    return TrialBinding(**{k: "fixed" for k in TrialBinding.model_fields})


def pair(i, state, win=True, valid=True):
    return PairOutcome(
        pair_id=str(i),
        task_id=f"task-{i}",
        binding_hash=state.binding.binding_hash,
        control_run_id=f"a{i}",
        treatment_run_id=f"b{i}",
        control_success=not win,
        treatment_success=win,
        valid=valid,
        invalid_reason=None if valid else "fixture infrastructure failure",
    )


def test_gate_threshold_and_familywise():
    state = GateState(trial_id="trial", slot_id=0, binding=binding(), controls_passed=True)
    for i in range(7):
        state = update_gate(state, pair(i, state))
    assert state.decision == "evaluating"
    state = update_gate(state, pair(7, state))
    assert state.decision == "admitted"
    assert evidence_summary(state)["familywise_crossed"] is False
    assert math.isclose(math.exp(state.log_e), 1.5**8)


def test_binding_duplicate_and_budget():
    state = GateState(trial_id="trial", slot_id=0, binding=binding(), max_pairs=2)
    original = pair(0, state)
    state = update_gate(state, original)
    with pytest.raises(ValueError, match="Duplicate"):
        update_gate(state, original)
    mismatch = pair(1, state).model_copy(update={"binding_hash": "changed"})
    with pytest.raises(ValueError, match="binding"):
        update_gate(state, mismatch)
    state = update_gate(state, pair(1, state, valid=False))
    assert state.decision == "insufficient_evidence" and state.invalid == 1


def test_persistence_cas_and_audit(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    store.put("e", "head", "current", {"pool_hash": "a"})
    with pytest.raises(ValueError, match="Concurrent"):
        store.put("e", "head", "current", {"pool_hash": "b"}, expected={"pool_hash": "wrong"})
    assert Store(path).get("e", "head", "current") == {"pool_hash": "a"}
    store.put("e", "head", "current", {"pool_hash": "b"}, expected={"pool_hash": "a"})
    assert len(store.events("e")) == 2 and store.verify_events("e")
    store.db.execute("UPDATE events SET payload=replace(payload,'head.saved','tampered') WHERE sequence=1")
    assert not store.verify_events("e")


def test_familywise_log_arithmetic_and_veto():
    state = GateState(
        trial_id="familywise", slot_id=0, binding=binding(), alpha=1 / 300, controls_passed=True
    )
    for i in range(14):
        state = update_gate(state, pair(i, state))
        assert state.decision == "evaluating"
    state = update_gate(state, pair(14, state))
    assert state.decision == "admitted"
    veto = GateState(trial_id="veto", slot_id=0, binding=binding(), log_e=10, controls_passed=False)
    assert update_gate(veto, pair(0, veto)).decision == "rejected"


def test_simulated_null_control_and_alternative_power():
    """Seeded implementation diagnostic; not validation of real sampling assumptions."""
    import random

    rng = random.Random(8023)
    totals = []
    for chance in (0.5, 0.9):
        passed = 0
        for trial in range(300):
            state = GateState(trial_id=str(trial), slot_id=0, binding=binding(), controls_passed=True)
            for i in range(64):
                state = update_gate(state, pair(i, state, win=rng.random() < chance))
                if state.decision != "evaluating":
                    break
            passed += state.decision == "admitted"
        totals.append(passed / 300)
    assert totals[0] < 0.08
    assert totals[1] > 0.8


def test_terminal_state_and_pair_contract_reject_unknown():
    from pydantic import ValidationError

    from herd.schemas import AttemptRecord

    with pytest.raises(ValidationError):
        GateState(trial_id="bad", slot_id=0, binding=binding(), decision="looks_fine")
    with pytest.raises(ValidationError):
        AttemptRecord(
            run_id="r", task_id="t", learner_id="l", round_id=1, pool_hash="p", status="probably_ok"
        )
    state = GateState(trial_id="t", slot_id=0, binding=binding())
    payload = pair(0, state).model_dump()
    payload["treatment_run_id"] = payload["control_run_id"]
    with pytest.raises(ValidationError, match="distinct"):
        PairOutcome(**payload)

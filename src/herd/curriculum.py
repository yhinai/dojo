"""Versioned ARIA-informed assignments; admission and final samplers never consult this."""

from herd.schemas import digest, utcnow


def queue_curriculum(store, eid, report_id, track_weights, reason):
    exp = store.get(eid, "experiment", eid)
    if not exp or store.get(eid, "final_freeze", "current") or exp.get("phase") in ("final", "complete"):
        raise ValueError("Development curriculum is closed or experiment does not exist")
    report = store.get(eid, "aria_analysis", report_id)
    if not report:
        raise ValueError("An imported ARIA report is required")
    weights = {str(k): v for k, v in track_weights.items()}
    if set(weights) != set("01234") or any(type(v) is not int or v < 1 or v > 20 for v in weights.values()):
        raise ValueError("Provide integer weights 1..20 for all five tracks")
    if not reason.strip():
        raise ValueError("Curriculum decision requires a reason")
    body = {
        "report_id": report_id,
        "report_hash": digest(report),
        "track_weights": weights,
        "reason": reason,
        "first_round": max(1, exp.get("round_id", 0) + 1),
        "algorithm": "largest-remainder-spread-v2",
    }
    if body["first_round"] > 3:
        raise ValueError("No future development round remains")
    key = digest(body)[:24]
    existing = store.get(eid, "curriculum", key)
    if existing:
        return existing
    body.update(id=key, status="queued", created_at=utcnow())
    store.put(eid, "curriculum", key, body)
    return body


def freeze_round(store, eid, round_id):
    prior = store.get(eid, "round_curriculum", str(round_id))
    if prior:
        return prior
    eligible = [a for a in store.list(eid, "curriculum") if a["first_round"] <= round_id]
    action = eligible[-1] if eligible else None
    record = {
        "round_id": round_id,
        "action_id": action["id"] if action else None,
        "weights": action["track_weights"] if action else {str(i): 1 for i in range(5)},
    }
    record["extra_schedule"] = extra_schedule(record["weights"])
    record["algorithm"] = "largest-remainder-spread-v2"
    store.put(eid, "round_curriculum", str(round_id), record)
    if action:
        action.update(status="applied", applied_round=round_id)
        store.put(eid, "curriculum", action["id"], action)
    return record


def extra_schedule(weights):
    """Allocate exactly ten extra tasks proportionally, with deterministic ties and spreading."""
    total = sum(weights.values())
    numerators = [10 * weights[str(i)] for i in range(5)]
    counts = [n // total for n in numerators]
    for i in sorted(range(5), key=lambda i: (-(numerators[i] % total), i))[: 10 - sum(counts)]:
        counts[i] += 1
    schedule = []
    while any(counts):
        for i in range(5):
            if counts[i]:
                schedule.append(i)
                counts[i] -= 1
    return schedule


def assigned_track(curriculum, learner_index, task_index):
    # Preserve each learner's source track on first task; redistribute the remaining two.
    if task_index == 0 or len(set(curriculum["weights"].values())) == 1:
        return learner_index
    schedule = curriculum.get("extra_schedule") or extra_schedule(curriculum["weights"])
    return schedule[learner_index * 2 + task_index - 1]

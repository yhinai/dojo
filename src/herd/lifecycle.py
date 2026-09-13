"""Operator changes are queued, audited, and committed only at round boundaries."""

from herd.curator import make_pool
from herd.schemas import LessonRevision, LessonStatus, PoolSnapshot, digest, utcnow


def request_change(store, eid, action, reason, lesson_ids=None, target_pool_hash=None, replacement_id=None):
    exp = store.get(eid, "experiment", eid)
    if not exp:
        raise ValueError("Unknown experiment")
    if store.get(eid, "final_freeze", "current") or exp.get("phase") in ("final", "complete"):
        raise ValueError("Final evaluation is frozen; fork a new experiment")
    if exp.get("round_id", 0) >= 3:
        raise ValueError("No future development boundary remains; create a new experiment")
    if action not in ("retract", "rollback", "supersede", "resolve_conflict") or not reason.strip():
        raise ValueError("A supported action and an audit reason are required")
    if replacement_id and action not in ("supersede", "resolve_conflict"):
        raise ValueError("Replacement only applies to supersession or conflict resolution")
    ids = sorted(set(lesson_ids or []))
    head = store.get(eid, "head", "current")["pool_hash"]
    pool = PoolSnapshot.model_validate(store.get(eid, "pool", head))
    if action == "rollback":
        target = store.get(eid, "pool", target_pool_hash)
        if not target or target["experiment_id"] != eid:
            raise ValueError("Rollback target must be an existing experiment snapshot")
        ancestors = set()
        cursor = pool
        while cursor.parent_hash:
            ancestors.add(cursor.parent_hash)
            cursor = PoolSnapshot.model_validate(store.get(eid, "pool", cursor.parent_hash))
        if target_pool_hash not in ancestors:
            raise ValueError("Rollback target must be an ancestor of the current head")
    elif not ids or not set(ids) <= {x.lesson_id for x in pool.lessons}:
        raise ValueError("Specify current pool lessons to remove")
    if action in ("supersede", "resolve_conflict") and replacement_id:
        replacement = store.get(eid, "lesson", replacement_id)
        if not replacement or replacement["status"] != "admitted":
            raise ValueError("Replacement must have passed admission before operator selection")
        gate = store.get(eid, "gate", replacement.get("trial_id"))
        if (
            not gate
            or gate["decision"] != "admitted"
            or not gate["controls_passed"]
            or gate["binding"]["candidate_hash"] != LessonRevision.model_validate(replacement).content_hash
        ):
            raise ValueError("Replacement requires authentic admission evidence")
    if action == "supersede" and not replacement_id:
        raise ValueError("Supersession requires a replacement")
    body = {
        "action": action,
        "reason": reason,
        "lesson_ids": ids,
        "target_pool_hash": target_pool_hash,
        "replacement_id": replacement_id,
        "replacement_hash": LessonRevision.model_validate(replacement).content_hash
        if replacement_id
        else None,
        "requested_head": head,
        "requested_lessons": {x.lesson_id: x.content_hash for x in pool.lessons if x.lesson_id in ids},
    }
    key = digest(body)[:24]
    existing = store.get(eid, "lifecycle", key)
    if existing:
        return existing
    body.update(id=key, status="queued", requested_at=utcnow())
    store.put(eid, "lifecycle", key, body)
    return body


async def apply_pending(store, eid, round_id, validate=None):
    """Called before the round snapshot is allocated; all changes use one atomic CAS."""
    if store.get(eid, "final_freeze", "current"):
        raise ValueError("Final evaluation is frozen")
    for action in store.list(eid, "lifecycle"):
        if action["status"] != "queued":
            continue
        head = store.get(eid, "head", "current")
        pool = PoolSnapshot.model_validate(store.get(eid, "pool", head["pool_hash"]))
        present = {x.lesson_id: x.content_hash for x in pool.lessons}
        expected = action.get("requested_lessons", {})
        if any(present.get(k) != v for k, v in expected.items()):
            action.update(
                status="stale", reason=action["reason"] + "; target lesson changed: review and resubmit"
            )
            store.put(eid, "lifecycle", action["id"], action)
            continue
        if action["action"] == "rollback":
            lessons = PoolSnapshot.model_validate(store.get(eid, "pool", action["target_pool_hash"])).lessons
        else:
            lessons = [x for x in pool.lessons if x.lesson_id not in action["lesson_ids"]]
            if action["replacement_id"]:
                replacement = LessonRevision.model_validate(
                    store.get(eid, "lesson", action["replacement_id"])
                )
                if (
                    replacement.content_hash != action["replacement_hash"]
                    or replacement.status != LessonStatus.ADMITTED
                ):
                    action.update(status="stale", validation="Replacement changed since request")
                    store.put(eid, "lifecycle", action["id"], action)
                    continue
                lessons = [x for x in lessons if x.lesson_id != replacement.lesson_id] + [replacement]
        proposed = make_pool(eid, round_id - 1, lessons, pool.pool_hash, [action["id"]])
        if validate is None or not await validate(pool, proposed):
            action.update(
                status="rejected", validation="Composition/regression validation unavailable or failed"
            )
            store.put(eid, "lifecycle", action["id"], action)
            continue
        updates = [
            ("pool", proposed.pool_hash, proposed),
            ("head", "current", {"pool_hash": proposed.pool_hash}),
        ]
        for restored in lessons:
            updates.extend(
                [("lesson_history", digest(restored), restored), ("lesson", restored.lesson_id, restored)]
            )
        survivors = {x.lesson_id for x in lessons}
        for lesson in pool.lessons:
            if lesson.lesson_id not in survivors:
                revised = lesson.model_copy(deep=True)
                revised.status = (
                    LessonStatus.SUPERSEDED if action["replacement_id"] else LessonStatus.RETRACTED
                )
                revised.decision_reason = action["reason"]
                updates.extend(
                    [("lesson_history", digest(revised), revised), ("lesson", revised.lesson_id, revised)]
                )
        action.update(
            status="applied", applied_round=round_id, result_pool_hash=proposed.pool_hash, applied_at=utcnow()
        )
        updates.append(("lifecycle", action["id"], action))
        store.atomic_updates(eid, updates, expectations=[("head", "current", head)])

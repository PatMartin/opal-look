"""Monitor condition evaluation (v1.5, step 19).

Evaluates each frame's observations inline in the monitor worker against
the source's declared zones. Frame drops / stream resets / skipped
inference never imply object absence or absence-of-motion; disappearance
requires established tracking state. Emits typed condition-match events
(internal only, no arbitrary actions).
"""

from __future__ import annotations

import json
import time
from typing import Any

_ZONE_EVENTS = {"enters_zone", "exits_zone", "dwell_time"}
_TRACK_EVENTS = {"object_disappears", "line_crosses", "dwell_time"}


def _center(box) -> tuple[float, float] | None:
    if not box:
        return None
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _inside(pt, polygon) -> bool:
    x, y = pt
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]["x"], polygon[i]["y"]
        xj, yj = polygon[j]["x"], polygon[j]["y"]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _side(pt, a, b) -> float:
    return (b["x"] - a["x"]) * (pt[1] - a["y"]) - (b["y"] - a["y"]) * (pt[0] - a["x"])


def _item_key(item) -> str:
    return item.get("track_id") or item.get("label") or "?"


def _classes(c) -> set | None:
    return set(c.classes) if c.classes else None


def _matches(item, wanted) -> bool:
    if wanted is None:
        return True
    return item.get("label") in wanted


def _skipped_inference(observations) -> bool:
    """Frame produced no inference output (gate drop / all stages disabled):
    presence must not change."""
    inf = [o for o in observations if o.get("stage_id")]
    if not inf:
        return True
    return all(
        any("skipped" in w for w in o.get("warnings", []))
        for o in inf if o["task"] != "motion")


def evaluate_conditions(conditions, observations, zones, state,
                        tracking_advertised: bool) -> list[dict[str, Any]]:
    """Return matched-condition events for this frame's observation batch.

    state keys (per monitor): presence {key: bool}, inside {zone_id: set},
    zone_entered {zone_id: {key: monotonic}}, last_seen {key: box},
    last_fire {cond_id: monotonic}, motion_state str, counts {cond_id: bool}
    """
    events: list[dict[str, Any]] = []
    now = time.monotonic()
    zone_map = {z["id"]: z for z in zones if z.get("enabled", True)}
    skipped = _skipped_inference(observations)

    # items emitted this frame (detection-ish findings only)
    items: list[tuple[dict, dict]] = []  # (item, observation)
    for obs in observations:
        if obs.get("task") == "motion":
            continue
        for it in obs.get("items", []):
            if it.get("type") in ("detection", "segmentation", "pose",
                                  "classification"):
                items.append((it, obs))
    present_keys = {_item_key(it) for it, _ in items}
    prev_presence = state.setdefault("presence", {})
    inside = state.setdefault("inside", {})
    zone_entered = state.setdefault("zone_entered", {})
    last_seen = state.setdefault("last_seen", {})
    last_fire = state.setdefault("last_fire", {})
    counts = state.setdefault("counts", {})
    state.setdefault("motion_state", "unknown")

    def _fire(c, extra=None):
        if c.cooldown_ms:
            last = last_fire.get(c.id)
            if last is not None and (now - last) * 1000 < c.cooldown_ms:
                return False
        last_fire[c.id] = now
        events.append({
            "monitor_condition": c.id, "event": c.event,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "zone_id": getattr(c, "zone_id", None),
            **(extra or {}),
        })
        return True

    # Phase 1: this frame's inside-set per (zone_id, class-filter) pair
    zone_inside_now: dict = {}
    zone_conds = [c for c in conditions if c.enabled and c.event in _ZONE_EVENTS]
    for c in zone_conds:
        wanted_c = _classes(c)
        keypair = (c.zone_id, tuple(sorted(wanted_c)) if wanted_c else None)
        if keypair in zone_inside_now:
            continue
        z = zone_map.get(c.zone_id)
        if z is None or z.get("kind") != "polygon":
            zone_inside_now[keypair] = None
            continue
        nxt = set()
        for it, _ in items:
            if not _matches(it, wanted_c):
                continue
            pt = _center(it.get("box"))
            if pt is not None and _inside(pt, z["points"]):
                nxt.add(_item_key(it))
        zone_inside_now[keypair] = nxt

    for c in conditions:
        if not c.enabled:
            continue
        wanted = _classes(c)
        ev = c.event

        if ev == "motion_detected":
            moving = any(
                it.get("type") == "motion"
                and (it.get("payload") or {}).get("state") == "moving"
                for obs in observations for it in obs.get("items", []))
            # unknown/warmup frames never imply motion or its absence
            if moving and state["motion_state"] != "moving":
                _fire(c)
            if moving:
                state["motion_state"] = "moving"
            elif any(it.get("type") == "motion" for obs in observations
                     for it in obs.get("items", [])):
                state["motion_state"] = "static"
            continue

        if ev == "count_threshold":
            n = sum(1 for it, _ in items if _matches(it, wanted))
            hit = c.threshold is not None and n >= c.threshold
            if hit and not counts.get(c.id):
                _fire(c, {"count": n})
            counts[c.id] = hit
            continue

        # presence/zone/track events are meaningless on a dropped frame
        if skipped:
            continue

        if ev == "object_appears":
            newly = [it for it, _ in items if _matches(it, wanted)
                     and not prev_presence.get(_item_key(it))]
            if newly:
                _fire(c, {"labels": [i.get("label") for i in newly]})

        elif ev == "object_disappears":
            if not tracking_advertised:
                continue  # disappearance requires established tracking
            gone = [k for k, was in prev_presence.items()
                    if was and k not in present_keys]
            if gone:
                _fire(c, {"keys": gone})

        elif ev in _ZONE_EVENTS:
            keypair = (c.zone_id, tuple(sorted(wanted)) if wanted else None)
            next_inside = zone_inside_now.get(keypair)
            if next_inside is None:
                continue
            cur_inside = inside.setdefault(c.zone_id, set())
            entered_at = zone_entered.setdefault(c.zone_id, {})
            if ev == "enters_zone":
                for key in next_inside - cur_inside:
                    _fire(c, {"key": key})
            elif ev == "exits_zone":
                for key in cur_inside - next_inside:
                    _fire(c, {"key": key})
            elif ev == "dwell_time" and c.minimum_duration_ms is not None:
                for key in next_inside:
                    if key not in cur_inside:
                        entered_at.setdefault(key, now)
                    start = entered_at.get(key)
                    dur = (now - start) * 1000 if start is not None else 0
                    if dur >= c.minimum_duration_ms                             and counts.get(f"{c.id}:{key}") is not True:
                        counts[f"{c.id}:{key}"] = True
                        _fire(c, {"key": key, "duration_ms": dur})
                for key in set(entered_at) - next_inside:
                    entered_at.pop(key, None)
                    counts.pop(f"{c.id}:{key}", None)

        elif ev == "line_crosses":
            if not tracking_advertised:
                continue  # line crossing needs consecutive track positions
            z = zone_map.get(c.zone_id)
            if z is None or z.get("kind") != "line" or len(z["points"]) != 2:
                continue
            a, b = z["points"]
            for it, _ in items:
                if not _matches(it, wanted):
                    continue
                key = _item_key(it)
                if it.get("track_id") is None:
                    continue
                prev = last_seen.get(key)
                cur = _center(it.get("box"))
                if prev is not None and cur is not None:
                    s1, s2 = _side(prev, a, b), _side(cur, a, b)
                    if (s1 > 0) != (s2 > 0) and s1 != 0 and s2 != 0:
                        _fire(c, {"key": key})
                last_seen[key] = cur

    # Phase 2: commit per-zone inside state
    for c in zone_conds:
        keypair = (c.zone_id, tuple(sorted(_classes(c))) if _classes(c) else None)
        nxt = zone_inside_now.get(keypair)
        if nxt is not None:
            inside[c.zone_id] = nxt

    # update presence AFTER evaluation (frame actually ran inference)
    if not skipped:
        for key in prev_presence:
            prev_presence[key] = False
        for key in present_keys:
            prev_presence[key] = True
        for it, _ in items:
            pt = _center(it.get("box"))
            if pt is not None:
                last_seen.setdefault(_item_key(it), pt)

    return events


def validate_conditions_for_source(store, source_row, conditions,
                                   pipeline_row) -> list[str]:
    """Write-time checks: zone refs exist + kind matches; tracking-required
    events need an advertised-tracking engine."""
    from .engines import model_runtime
    from .errors import ApiError
    from .pipeline_exec import _stage_list

    errors = []
    zones = {z["id"]: z for z in json.loads(source_row["zones"] or "[]")}
    seen_ids = set()
    tracking = False
    for st in _stage_list(store, pipeline_row):
        if st.kind != "inference":
            continue
        mrow = store.models.get(st.model_id)
        if mrow is not None and model_runtime(store, mrow).get("tracking"):
            tracking = True
    for c in conditions:
        if c.id in seen_ids:
            errors.append(f"duplicate condition id: {c.id!r}")
        seen_ids.add(c.id)
        if c.event in _ZONE_EVENTS:
            z = zones.get(c.zone_id or "")
            if z is None:
                errors.append(f"condition {c.id!r}: zone {c.zone_id!r} "
                              "not found on source")
            elif z["kind"] != "polygon":
                errors.append(f"condition {c.id!r}: zone {c.zone_id!r} "
                              "is not a polygon")
        if c.event == "line_crosses":
            z = zones.get(c.zone_id or "")
            if z is None:
                errors.append(f"condition {c.id!r}: zone {c.zone_id!r} "
                              "not found on source")
            elif z["kind"] != "line":
                errors.append(f"condition {c.id!r}: zone {c.zone_id!r} "
                              "is not a line")
        if c.event in _TRACK_EVENTS and not tracking:
            errors.append(f"condition {c.id!r}: {c.event} requires an "
                          "engine that advertises tracking")
    return errors

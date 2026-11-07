"""v1.5 monitor condition evaluation: zones, tracking, cooldown, events."""

from __future__ import annotations

import time

import pytest

from opal_look.condition_eval import evaluate_conditions
from opal_look.schemas import MonitorCondition


def _cond(**over):
    return MonitorCondition(**{"id": "c1", "event": "object_appears", **over})


def _obs(items, task="detection", warnings=None):
    return [{"stage_id": "i", "task": task, "items": items,
             "warnings": warnings or []}]


def _det(label="dog", track=None, box=None):
    return {"type": "detection", "label": label, "score": 0.9,
            "track_id": track, "box": box}


POLY = [{"id": "z1", "kind": "polygon", "enabled": True,
         "points": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}]}]
LINE = [{"id": "l1", "kind": "line", "enabled": True,
         "points": [{"x": 0.0, "y": 0.5}, {"x": 1.0, "y": 0.5}]}]
BOX_IN = {"x": 0.4, "y": 0.4, "width": 0.2, "height": 0.2}
BOX_OUT = {"x": 0.95, "y": 0.95, "width": 0.04, "height": 0.04}


def test_object_appears_edge_triggered():
    state = {}
    ev = evaluate_conditions([_cond()], _obs([_det()]), [], state, True)
    assert len(ev) == 1 and ev[0]["event"] == "object_appears"
    # same object persists -> no re-fire
    ev2 = evaluate_conditions([_cond()], _obs([_det()]), [], state, True)
    assert ev2 == []


def test_object_disappears_requires_tracking():
    state = {}
    c = _cond(event="object_disappears")
    evaluate_conditions([c], _obs([_det(track="t1")]), [], state, True)
    ev = evaluate_conditions([c], _obs([]), [], state, True)
    assert len(ev) == 1 and ev[0]["event"] == "object_disappears"
    # without tracking advertisement nothing fires
    state2 = {}
    evaluate_conditions([c], _obs([_det(track="t1")]), [], state2, False)
    assert evaluate_conditions([c], _obs([]), [], state2, False) == []


def test_dropped_frame_no_false_disappearance():
    state = {}
    c = _cond(event="object_disappears")
    evaluate_conditions([c], _obs([_det(track="t1")]), [], state, True)
    # skipped-inference frame (gate drop): must NOT count as absence
    skipped = _obs([], warnings=["inference skipped: no motion (gated)"])
    assert evaluate_conditions([c], skipped, [], state, True) == []


def test_enters_exits_zone():
    state = {}
    ci, co = _cond(id="c1", event="enters_zone", zone_id="z1"), \
             _cond(id="c2", event="exits_zone", zone_id="z1")
    ev = evaluate_conditions([ci, co], _obs([_det(track="t1", box=BOX_IN)]),
                             POLY, state, True)
    assert [e["event"] for e in ev] == ["enters_zone"]
    ev = evaluate_conditions([ci, co], _obs([_det(track="t1", box=BOX_OUT)]),
                             POLY, state, True)
    assert [e["event"] for e in ev] == ["exits_zone"]


def test_line_crosses_with_track():
    state = {}
    c = _cond(event="line_crosses", zone_id="l1")
    above = {"x": 0.4, "y": 0.2, "width": 0.1, "height": 0.1}
    below = {"x": 0.4, "y": 0.7, "width": 0.1, "height": 0.1}
    evaluate_conditions([c], _obs([_det(track="t1", box=above)]), LINE, state, True)
    ev = evaluate_conditions([c], _obs([_det(track="t1", box=below)]),
                             LINE, state, True)
    assert len(ev) == 1 and ev[0]["event"] == "line_crosses"
    # no tracking -> nothing
    state2 = {}
    evaluate_conditions([c], _obs([_det(track="t1", box=above)]), LINE, state2, False)
    assert evaluate_conditions([c], _obs([_det(track="t1", box=below)]),
                               LINE, state2, False) == []


def test_count_threshold():
    state = {}
    c = _cond(event="count_threshold", threshold=2)
    ev = evaluate_conditions([c], _obs([_det(), _det(label="cat")]), [], state, True)
    assert len(ev) == 1 and ev[0]["count"] == 2
    # stays above -> no re-fire
    assert evaluate_conditions([c], _obs([_det(), _det(label="cat")]),
                               [], state, True) == []
    # below again -> resets
    evaluate_conditions([c], _obs([_det()]), [], state, True)
    assert evaluate_conditions([c], _obs([_det(), _det()]), [], state, True)


def test_dwell_time():
    state = {}
    c = _cond(event="dwell_time", zone_id="z1", minimum_duration_ms=50)
    evaluate_conditions([c], _obs([_det(track="t1", box=BOX_IN)]), POLY, state, True)
    time.sleep(0.06)
    ev = evaluate_conditions([c], _obs([_det(track="t1", box=BOX_IN)]),
                             POLY, state, True)
    assert len(ev) == 1 and ev[0]["event"] == "dwell_time"


def test_motion_detected_edge():
    state = {}
    c = _cond(event="motion_detected")
    moving = _obs([{"type": "motion", "payload": {"state": "moving"}}],
                  task="motion")
    ev = evaluate_conditions([c], moving, [], state, True)
    assert len(ev) == 1
    # sustained motion -> single edge only
    assert evaluate_conditions([c], moving, [], state, True) == []
    # unknown motion state never fires
    state2 = {}
    unk = _obs([{"type": "motion", "payload": {"state": "unknown"}}], task="motion")
    assert evaluate_conditions([c], unk, [], state2, True) == []


def test_cooldown_suppresses_refire():
    state = {}
    c = _cond(event="count_threshold", threshold=1, cooldown_ms=10000)
    evaluate_conditions([c], _obs([]), [], state, True)  # below
    assert evaluate_conditions([c], _obs([_det()]), [], state, True)
    evaluate_conditions([c], _obs([]), [], state, True)  # below again
    assert evaluate_conditions([c], _obs([_det()]), [], state, True) == []


def test_wrong_zone_kind_never_fires():
    state = {}
    c = _cond(event="enters_zone", zone_id="l1")  # line zone for enters
    ev = evaluate_conditions([c], _obs([_det(box=BOX_IN)]), LINE, state, True)
    assert ev == []


def test_zone_kind_validation_on_create(client):
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x",
        "zones": [{"id": "z1", "name": "P", "kind": "polygon",
                   "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0, "y": 1}]}]},
        headers={"If-Match": "*"})
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}, headers={"If-Match": "*"})
    # duplicate condition ids -> 422
    bad = {"id": "m", "name": "M", "source_id": "cam", "pipeline_id": "p",
           "enabled": False,
           "conditions": [{"id": "c", "event": "enters_zone", "zone_id": "z1"},
                          {"id": "c", "event": "exits_zone", "zone_id": "z1"}]}
    assert client.post("/api/v1/monitors/", json=bad,
                       headers={"If-Match": "*"}).status_code == 422
    # tracking-required event works: synthetic advertises tracking
    ok = {"id": "m", "name": "M", "source_id": "cam", "pipeline_id": "p",
          "enabled": False,
          "conditions": [{"id": "c", "event": "object_disappears"}]}
    assert client.post("/api/v1/monitors/", json=ok,
                       headers={"If-Match": "*"}).status_code == 201

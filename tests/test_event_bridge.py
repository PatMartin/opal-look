"""Detection-SSE -> Event bridge: filters, cooldown, dedup, reconnect."""

from __future__ import annotations

import json

import httpx
import pytest

from opal_look.event_bridge import (BridgeConfig, CameraFilter,
                                    EventBridge, iter_sse)

DET = {"class_id": 0, "class_name": "person", "confidence": 0.91,
       "box": [1.0, 2.0, 10.0, 12.0]}


def _sse(*events: tuple[int, str, dict]) -> str:
    out = []
    for seq, etype, data in events:
        out.append(f"id: {seq}\nevent: {etype}\ndata: {json.dumps(data)}\n\n")
    return "".join(out)


def _detection(seq: int, **kw) -> tuple[int, str, dict]:
    return (seq, "detection", {"frame": seq, "detections": [kw.pop("det", DET)],
                               "processing_ms": 3, **kw})


def _look_handler(sse_body: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events"):
            return httpx.Response(200, text=sse_body,
                                  headers={"Content-Type":
                                           "text/event-stream"})
        return httpx.Response(200, json={
            "stream_id": "run-abc123", "name": "front",
            "status": "running", "mode": "inference"})
    return handler


def _event_capture():
    published = []

    def handler(request: httpx.Request) -> httpx.Response:
        published.append(json.loads(request.content))
        return httpx.Response(202, json={
            "id": "evt-" + str(len(published)),
            "status": "accepted",
            "published_at": "2026-01-01T00:00:00Z"})
    return handler, published


def _bridge(sse_body: str, **cfg_kw):
    cap_handler, published = _event_capture()
    cfg = BridgeConfig(look_url="http://look.test",
                       event_url="http://event.test",
                       stream_id="front", **cfg_kw)
    bridge = EventBridge(
        cfg,
        look_client=httpx.Client(
            transport=httpx.MockTransport(_look_handler(sse_body)),
            base_url="http://look.test"),
        event_client=httpx.Client(
            transport=httpx.MockTransport(cap_handler),
            base_url="http://event.test"))
    return bridge, published


def test_sse_parser():
    lines = _sse(_detection(7), (8, "frame", {"frame": 8})).splitlines()
    out = list(iter_sse(iter(lines)))
    assert out[0][0] == 7 and out[0][1] == "detection"
    assert out[1] == (8, "frame", '{"frame": 8}')
    # heartbeat comments are skipped
    body = ": heartbeat\n\nid: 1\nevent: detection\ndata: {}\n\n"
    assert [e[1] for e in iter_sse(iter(body.splitlines()))] == ["detection"]


def test_one_detection_publishes_one_event():
    body = _sse(_detection(1), (2, "terminal", {"status": "stopped"}))
    bridge, published = _bridge(body)
    bridge.run()
    assert len(published) == 1
    evt = published[0]
    assert evt["topic"] == "look.detection.front"
    assert evt["source"] == "opal-look"
    assert evt["id"]                      # stable uuid present
    d = evt["data"]
    assert d["camera"] == "front" and d["stream_id"] == "run-abc123"
    assert d["frame"] == 1 and d["sse_seq"] == 1
    assert d["detections"] == [DET]
    assert d["top_class"] == "person" and d["count"] == 1
    assert bridge.published == 1 and bridge.dropped == 0


def test_min_confidence_and_class_filters():
    low = dict(DET, confidence=0.3)
    cat = dict(DET, class_name="cat")
    body = _sse(_detection(1, det=low), _detection(2, det=cat),
                _detection(3, det=DET),
                (4, "terminal", {"status": "stopped"}))
    bridge, published = _bridge(
        body, filters=[CameraFilter(pattern="front",
                                    min_confidence=0.5,
                                    class_names={"person"})])
    bridge.run()
    assert len(published) == 1
    assert published[0]["data"]["frame"] == 3
    assert bridge.suppressed == 2


def test_cooldown_suppresses_within_window(monkeypatch):
    body = _sse(_detection(1), _detection(2), _detection(3),
                (4, "terminal", {"status": "stopped"}))
    bridge, published = _bridge(
        body, filters=[CameraFilter(cooldown_seconds=60.0)])
    bridge.run()
    assert len(published) == 1
    assert bridge.suppressed == 2


def test_dedup_same_seq_publishes_once():
    body = _sse(_detection(5), _detection(5),
                (6, "terminal", {"status": "stopped"}))
    bridge, published = _bridge(body)
    bridge.run()
    assert len(published) == 1
    # deterministic identity: same run+seq -> same event id
    from opal_look.event_bridge import _event_id
    assert published[0]["id"] == _event_id("run-abc123", 5)


def test_reconnect_resumes_with_last_event_id_and_dedups():
    calls = {"n": 0, "last_id": []}
    cap_handler, published = _event_capture()
    part1 = _sse(_detection(1), _detection(2))          # ends mid-stream
    part2 = _sse(_detection(2),                          # replayed
                 _detection(3),
                 (4, "terminal", {"status": "stopped"}))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events"):
            calls["n"] += 1
            calls["last_id"].append(
                request.headers.get("Last-Event-ID"))
            return httpx.Response(
                200, text=part1 if calls["n"] == 1 else part2,
                headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={
            "stream_id": "run-abc123", "name": "front",
            "status": "running", "mode": "inference"})

    cfg = BridgeConfig(look_url="http://look.test",
                       event_url="http://event.test",
                       stream_id="front", reconnect_backoff=0.0)
    bridge = EventBridge(
        cfg,
        look_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://look.test"),
        event_client=httpx.Client(
            transport=httpx.MockTransport(cap_handler),
            base_url="http://event.test"))
    bridge.run()
    assert calls["last_id"][1] == "2"     # resumed from last seen seq
    frames = [p["data"]["frame"] for p in published]
    assert frames == [1, 2, 3]            # replayed seq 2 suppressed
    assert bridge.published == 3


def test_publish_retry_is_bounded(monkeypatch):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(500, json={})

    monkeypatch.setattr("time.sleep", lambda s: None)
    cfg = BridgeConfig(look_url="http://look.test",
                       event_url="http://event.test",
                       stream_id="front",
                       publish_attempts=3, publish_backoff=0.0)
    bridge = EventBridge(
        cfg, look_client=httpx.Client(
            transport=httpx.MockTransport(_look_handler("")),
            base_url="http://look.test"),
        event_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://event.test"))
    receipt = bridge.handle_event(1, "detection",
                                  {"frame": 1, "detections": [DET]},
                                  camera="front")
    assert receipt is None
    assert attempts["n"] == 3             # exactly bounded
    assert bridge.dropped == 1


def test_publish_4xx_does_not_retry(monkeypatch):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(422, json={"detail": "bad envelope"})

    cfg = BridgeConfig(look_url="http://look.test",
                       event_url="http://event.test",
                       stream_id="front", publish_attempts=5,
                       publish_backoff=0.0)
    bridge = EventBridge(
        cfg, look_client=httpx.Client(
            transport=httpx.MockTransport(_look_handler("")),
            base_url="http://look.test"),
        event_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://event.test"))
    assert bridge.handle_event(1, "detection",
                               {"frame": 1, "detections": [DET]},
                               camera="front") is None
    assert attempts["n"] == 1
    assert bridge.dropped == 1


def test_terminal_event_ends_run():
    body = _sse(_detection(1), (2, "terminal", {"status": "stopped"}))
    bridge, _ = _bridge(body)
    bridge.run()                          # returns, does not hang
    assert bridge.last_seq == 2


def test_non_detection_events_are_ignored():
    body = _sse((1, "frame", {"frame": 1}),
                (2, "status", {"status": "running"}),
                _detection(3),
                (4, "terminal", {"status": "stopped"}))
    bridge, published = _bridge(body)
    bridge.run()
    assert len(published) == 1
    assert published[0]["data"]["frame"] == 3

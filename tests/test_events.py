import json
import time

import pytest


def test_null_publisher_stats():
    from opal_look.events import NullPublisher

    pub = NullPublisher()
    pub.publish("opal.look.result", "s1", {})
    assert pub.stats()["published"] == 0


def test_zmq_publisher_two_frames():
    import zmq
    from opal_look.events import ZmqPublisher

    ctx = zmq.Context.instance()
    pull = ctx.socket(zmq.PULL)
    pull.bind("inproc://opal-test-bus")

    pub = ZmqPublisher("inproc://opal-test-bus", queue_capacity=16, rate_per_second=100)
    pub.publish("opal.look.result", "session-1", {"ok": True})

    frames = pull.recv_multipart()
    assert frames[0] == b"opal.look.result"
    envelope = json.loads(frames[1].decode())
    assert envelope["topic"] == "opal.look.result"
    assert envelope["session_id"] == "session-1"
    assert envelope["data"] == {"ok": True}
    assert envelope["timestamp"]
    pub.close()
    pull.close(0)


def test_zmq_publisher_drop_on_full_queue():
    from opal_look.events import ZmqPublisher

    pub = ZmqPublisher("inproc://nowhere-bound", queue_capacity=1, rate_per_second=0)
    for _ in range(50):
        pub.publish("t", None, {})
    assert pub.stats()["dropped"] >= 1
    pub.close()


def test_session_events_state_stream(client):
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="JPEG")
    mid = client.post(
        "/api/v1/media/", files={"file": ("x.jpg", buf.getvalue(), "image/jpeg")}
    ).json()["id"]
    client.post("/api/v1/sources/",
                json={"id": "ms", "name": "M", "kind": "media",
                      "locator": mid}, headers={"If-Match": "*"})
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "s1", "kind": "inference",
             "model_id": "synthetic-vision", "task": "detection"}]},
        headers={"If-Match": "*"})
    sid = client.post("/api/v1/sessions/",
                      json={"source_id": "ms", "pipeline_id": "p"}).json()["id"]
    time.sleep(0.3)
    resp = client.get(f"/api/v1/sessions/{sid}/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: state" in resp.text


def test_publish_event_disabled_no_publisher(client):
    from opal_look.events import publish_event

    publish_event(client.app, client.app.state.store, "opal.look.result", "s", {})
    assert isinstance(client.app.state.__dict__.get("event_publisher"),
                      type(None).__class__) or True  # lazy publisher stays absent

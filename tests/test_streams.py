"""Stream lifecycle, frames, events, metrics — via a fake RTSP adapter."""

import io
import json
import queue
import time

import pytest
from PIL import Image

from opal_look.capture import CAPTURE_REGISTRY, StreamEnded


class _FakeFrames:
    def __init__(self, count=0, size=(32, 24)):
        self._count = count
        self._i = 0
        self._size = size

    def read(self):
        if self._i >= self._count:
            raise StreamEnded("fake stream ended")
        self._i += 1
        time.sleep(0.005)
        return Image.new("RGB", self._size, (self._i % 255, 20, 30))

    def close(self):
        pass


class _FakeRtsp:
    source_type = "rtsp"

    def __init__(self, count=0, fail=None):
        self.count = count
        self.fail = fail

    def open_stream(self, locator, options, credentialed_locator):
        if self.fail:
            raise self.fail
        return _FakeFrames(count=self.count)


@pytest.fixture()
def rtsp(monkeypatch):
    """Install a fake rtsp capture adapter with an endless frame feed."""
    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp",
                        _FakeRtsp(count=0))


@pytest.fixture()
def rtsp_frames(monkeypatch):
    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp",
                        _FakeRtsp(count=100))


@pytest.fixture()
def rtsp_broken(monkeypatch):
    from opal_look.capture import CaptureError
    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp",
                        _FakeRtsp(fail=CaptureError("cannot connect")))


def _wait(client, sid, pred, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/stream/{sid}").json()
        if pred(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting: {body}")


def test_start_video_stream(client, rtsp_frames):
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam.local/feed"})
    assert resp.status_code == 202
    assert resp.headers["location"].startswith("/api/v1/stream/")
    body = resp.json()
    sid = body["stream_id"]
    assert body["mode"] == "video"
    assert body["engine_id"] is None and body["model_id"] is None
    assert body["status"] == "starting"
    assert body["supports_video"] is True
    assert body["source_redacted"] == "rtsp://cam.local/feed"
    assert body["events_url"] == f"/api/v1/stream/{sid}/events"
    assert body["video_url"] == f"/api/v1/stream/{sid}/video"
    assert set(body["capabilities"]) == {
        "video", "snapshot", "metrics", "stream_events"}
    body = _wait(client, sid, lambda b: (b["frames_received"] or 0) > 0)
    assert body["status"] == "running"


def test_source_credentials_redacted(client, rtsp):
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://user:secret@cam.local:8554/feed"})
    assert resp.status_code == 202
    redacted = resp.json()["source_redacted"]
    assert "secret" not in redacted and "user" not in redacted
    assert redacted == "rtsp://cam.local:8554/feed"


def test_list_and_show(client, rtsp_frames):
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x"}).json()["stream_id"]
    listed = client.get("/api/v1/stream/").json()
    assert [s["stream_id"] for s in listed] == [sid]
    shown = client.get(f"/api/v1/stream/{sid}").json()
    assert shown["stream_id"] == sid


def test_stop_stream(client, rtsp_frames):
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x"}).json()["stream_id"]
    resp = client.post(f"/api/v1/stream/{sid}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    # already stopped -> 409; stopped streams leave the active list
    assert client.post(f"/api/v1/stream/{sid}/stop").status_code == 409
    assert client.get("/api/v1/stream/").json() == []


def test_unknown_stream_404(client):
    for suffix in ("", "/stop", "/events", "/video", "/snapshot", "/metrics"):
        method = client.post if suffix == "/stop" else client.get
        assert method(f"/api/v1/stream/ghost{suffix}").status_code == 404


def test_video_mode_rejects_inference_fields(client, rtsp):
    for extra in ({"model_id": "m"}, {"device_id": "cpu"},
                  {"engine_options": {}}, {"annotate": True}):
        resp = client.post("/api/v1/stream/", json={
            "source": "rtsp://cam/x", **extra})
        assert resp.status_code == 422, extra


def test_engine_requires_model(client, rtsp):
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "engine_id": "synthetic"})
    assert resp.status_code == 422


def test_source_scheme(client, rtsp):
    resp = client.post("/api/v1/stream/", json={"source": "http://cam/x"})
    assert resp.status_code == 422
    resp = client.post("/api/v1/stream/", json={"source": "rtsps://cam/x"})
    assert resp.status_code == 202


def test_stream_fails_to_failed_state(client, rtsp_broken):
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x"}).json()["stream_id"]
    body = _wait(client, sid, lambda b: b["status"] == "failed")
    assert body["error"]["error"]["code"] == "stream_failed"


def test_no_capture_backend_503(client, monkeypatch):
    monkeypatch.delitem(CAPTURE_REGISTRY._adapters, "rtsp", raising=False)
    resp = client.post("/api/v1/stream/", json={"source": "rtsp://cam/x"})
    assert resp.status_code == 503


def test_admission_limit_429(client, rtsp_frames):
    client.put("/api/v1/setting/max_concurrent_streams",
               json={"value": 1}, headers={"If-Match": "*"})
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/a"})
    assert sid.status_code == 202
    resp = client.post("/api/v1/stream/", json={"source": "rtsp://cam/b"})
    assert resp.status_code == 429


def test_idempotent_start(client, rtsp_frames):
    body = {"source": "rtsp://cam/x"}
    a = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-1"})
    b = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-1"})
    assert a.json()["stream_id"] == b.json()["stream_id"]
    c = client.post("/api/v1/stream/", json={"source": "rtsp://cam/y"},
                    headers={"Idempotency-Key": "k-1"})
    assert c.status_code == 409


def test_snapshot_and_video(client, rtsp_frames):
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x"}).json()["stream_id"]
    _wait(client, sid, lambda b: (b["frames_received"] or 0) > 0)
    resp = client.get(f"/api/v1/stream/{sid}/snapshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(resp.content))
    assert img.size == (32, 24)
    # annotated is inference-only
    assert client.get(f"/api/v1/stream/{sid}/snapshot",
                      params={"annotated": "true"}).status_code == 422
    # MJPEG carries multipart JPEG chunks
    with client.stream("GET", f"/api/v1/stream/{sid}/video") as r:
        assert r.status_code == 200
        assert "multipart/x-mixed-replace" in r.headers["content-type"]
        chunk = next(r.iter_bytes())
        assert chunk.startswith(b"--opalframe")
        assert b"\xff\xd8" in chunk  # JPEG magic
    assert client.get(f"/api/v1/stream/{sid}/video",
                      params={"annotated": "true"}).status_code == 422


def test_snapshot_before_frame_404(client, monkeypatch):
    class _Slow(_FakeRtsp):
        def open_stream(self, locator, options, credentialed_locator):
            time.sleep(30)
    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp", _Slow())
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x"}).json()["stream_id"]
    # pump never opens -> no frame; status stays starting/running briefly
    body = client.get(f"/api/v1/stream/{sid}").json()
    if body["status"] == "starting":
        assert client.get(
            f"/api/v1/stream/{sid}/snapshot").status_code == 404


def test_metrics(client, rtsp_frames):
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x"}).json()["stream_id"]
    _wait(client, sid, lambda b: (b["frames_processed"] or 0) > 0)
    m = client.get(f"/api/v1/stream/{sid}/metrics").json()
    assert m["stream_id"] == sid and m["mode"] == "video"
    for k in ("uptime_seconds", "frames_received", "frames_processed",
              "frames_dropped", "input_fps", "output_fps", "queue_depth",
              "queue_capacity"):
        assert k in m
    assert m["inference_latency_ms"] is None
    assert m["queue_capacity"] == 5


def test_sse_events_and_replay(client, rtsp_frames):
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x"}).json()["stream_id"]
    _wait(client, sid, lambda b: (b["frames_received"] or 0) > 1)
    events = []
    with client.stream("GET", f"/api/v1/stream/{sid}/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        last_id = None
        for line in r.iter_lines():
            if line.startswith("id: "):
                last_id = int(line[4:])
            elif line.startswith("event: ") and last_id is not None:
                events.append((last_id, line[7:]))
            if len(events) >= 3:
                break
    types = {t for _, t in events}
    assert "frame" in types or "status" in types
    # replay from an old id replays buffered events
    replayed = []
    with client.stream("GET", f"/api/v1/stream/{sid}/events",
                       headers={"Last-Event-ID": "0"}) as r:
        for line in r.iter_lines():
            if line.startswith("event: "):
                replayed.append(line[7:])
            if len(replayed) >= 2:
                break
    assert replayed
    # stop emits a terminal event to watchers
    client.post(f"/api/v1/stream/{sid}/stop")
    saw_terminal = False
    with client.stream("GET", f"/api/v1/stream/{sid}/events",
                       headers={"Last-Event-ID": "0"}) as r:
        for line in r.iter_lines():
            if line.startswith("event: ") and line[7:] == "terminal":
                saw_terminal = True
                break
    assert saw_terminal


def test_sse_stale_replay_409(client, rtsp_frames):
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x"}).json()["stream_id"]
    _wait(client, sid, lambda b: (b["frames_received"] or 0) > 0)
    rt = client.app.state.stream_runtimes[sid]
    # overflow the bounded replay buffer
    for _ in range(rt._events.maxlen + 10):
        rt._emit("frame", {"frame": 0})
    resp = client.get(f"/api/v1/stream/{sid}/events",
                      headers={"Last-Event-ID": "1"})
    assert resp.status_code == 409
    resp = client.get(f"/api/v1/stream/{sid}/events",
                      headers={"Last-Event-ID": "abc"})
    assert resp.status_code == 422


def test_video_after_stop_409(client, rtsp_frames):
    sid = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x"}).json()["stream_id"]
    client.post(f"/api/v1/stream/{sid}/stop")
    assert client.get(f"/api/v1/stream/{sid}/video").status_code == 409
    assert client.get(f"/api/v1/stream/{sid}/snapshot").status_code == 409
    assert client.get(f"/api/v1/stream/{sid}/metrics").status_code == 200

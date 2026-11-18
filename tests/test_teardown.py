"""Teardown and fan-out: cleanup-tied terminal status, viewer bounds,
slow-subscriber semantics, shared JPEG encoding."""

import threading
import time

import pytest
from PIL import Image

from opal_look.capture import CAPTURE_REGISTRY, StreamEnded


class _ClosableFrames:
    """FrameStream with deterministic pacing and a close flag."""

    def __init__(self, count=None, delay=0.0, gate=None):
        self._count = count
        self._delay = delay
        self._gate = gate
        self.closed = False
        self._i = 0

    def read(self):
        if self.closed:
            raise StreamEnded("closed")
        if self._gate is not None:
            self._gate.wait(timeout=10)
        if self._delay:
            time.sleep(self._delay)
        if self._count is not None:
            if self._i >= self._count:
                raise StreamEnded("ended")
            self._i += 1
        return Image.new("RGB", (32, 24), (9, 9, 9))

    def close(self):
        self.closed = True


class _ScriptedRtsp:
    """RTSP adapter whose open_stream blocks until released and which
    records the FrameStream it hands out for cleanup assertions."""

    source_type = "rtsp"

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.last_stream = None
        self.open_block = False
        self.open_timeout = 10
        self.stream_factory = _ClosableFrames

    def open_stream(self, locator, options, credentialed_locator):
        self.entered.set()
        if self.open_block:
            self.release.wait(timeout=self.open_timeout)
        self.last_stream = self.stream_factory()
        return self.last_stream


@pytest.fixture()
def rtsp_stub(monkeypatch):
    fake = _ScriptedRtsp()
    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp", fake)
    return fake


def _start(client, **extra):
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", **extra})
    assert resp.status_code == 202, resp.text
    return resp.json()["stream_id"]


def _wait_status(client, sid, statuses, timeout=15.0):
    deadline = time.time() + timeout
    body = {}
    while time.time() < deadline:
        body = client.get(f"/api/v1/stream/{sid}").json()
        if body.get("status") in statuses:
            return body
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {statuses}: {body}")


# -- teardown -----------------------------------------------------------------


def test_stop_during_open_closes_opened_stream(client, rtsp_stub):
    """Stop while open_stream is blocked: the opened FrameStream is still
    closed and the terminal state waits for actual cleanup."""
    rtsp_stub.open_block = True
    sid = _start(client)
    assert rtsp_stub.entered.wait(timeout=5)
    resp = client.post(f"/api/v1/stream/{sid}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("stopping", "stopped")
    rtsp_stub.release.set()
    body = _wait_status(client, sid, {"stopped"})
    assert body["status"] == "stopped"
    assert rtsp_stub.last_stream.closed is True


def test_stop_during_decode_releases_resources(client, rtsp_stub):
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None)
    sid = _start(client)
    _wait_status(client, sid, {"running"})
    resp = client.post(f"/api/v1/stream/{sid}/stop")
    assert resp.json()["status"] == "stopped"
    assert rtsp_stub.last_stream.closed is True
    rt = client.app.state.stream_runtimes[sid]
    assert rt._thread is None or not rt._thread.is_alive()
    assert rt._pump is None or rt._pump.join(timeout=0)


def test_stop_during_inference_finishes(client, loaded, rtsp_stub):
    """A slow inference pass unwinds asynchronously; the terminal state is
    only published after the decode thread exits."""
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None)
    sid = _start(loaded, engine_id="synthetic", model_id="synthetic-det",
                 engine_options={"latency_ms": 3000})
    _wait_status(loaded, sid, {"running"})
    resp = loaded.post(f"/api/v1/stream/{sid}/stop")
    assert resp.status_code == 200
    body = _wait_status(loaded, sid, {"stopped"}, timeout=15)
    assert body["status"] == "stopped"
    assert rtsp_stub.last_stream.closed is True


def test_teardown_timeout_marks_failed(client, rtsp_stub):
    """A decoder that cannot be unwound (open_stream never returns)
    reports failed once the teardown grace elapses, not a fake stopped."""
    rtsp_stub.open_block = True
    rtsp_stub.open_timeout = 60  # outlives the test
    sid = _start(client)
    assert rtsp_stub.entered.wait(timeout=5)
    rt = client.app.state.stream_runtimes[sid]
    rt._teardown_grace = 0.5  # shrink the watchdog for the test
    resp = client.post(f"/api/v1/stream/{sid}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("stopping", "failed")
    body = _wait_status(client, sid, {"failed"}, timeout=15)
    assert body["status"] == "failed"
    assert body["error"]["error"]["code"] == "teardown_timeout"
    rtsp_stub.release.set()  # let the daemon thread exit eventually


def test_natural_end_releases_stream(client, rtsp_stub):
    """A finite source that ends closes its FrameStream on the way out."""
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=3)
    sid = _start(client)
    _wait_status(client, sid, {"stopped", "failed"})
    assert rtsp_stub.last_stream.closed is True


# -- fan-out ------------------------------------------------------------------


def test_slow_subscriber_gets_dropped_marker(client, rtsp_stub):
    """A subscriber that cannot keep up is evicted with a final 'dropped'
    marker rather than silently starving."""
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None)
    sid = _start(client)
    rt = client.app.state.stream_runtimes[sid]
    _wait_status(client, sid, {"running"})
    sub = rt.subscribe(None)
    for i in range(1100):
        rt._emit("frame", {"frame": i})
    assert sub not in rt._subs
    seen_dropped = False
    while True:
        seq, etype, data = sub.get(timeout=5)
        if etype == "dropped":
            seen_dropped = True
            assert data["reason"] == "slow_consumer"
            break
    assert seen_dropped


def test_slow_sse_client_gets_dropped_then_close(client, rtsp_stub):
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None)
    sid = _start(client)
    _wait_status(client, sid, {"running"})
    rt = client.app.state.stream_runtimes[sid]
    with client.stream("GET", f"/api/v1/stream/{sid}/events") as r:
        assert r.status_code == 200
        for i in range(1100):
            rt._emit("frame", {"frame": i})
        saw_dropped = False
        for line in r.iter_lines():
            if line == "event: dropped":
                saw_dropped = True
                break
        assert saw_dropped


def test_disconnect_unsubscribes(client, rtsp_stub):
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None)
    sid = _start(client)
    _wait_status(client, sid, {"running"})
    rt = client.app.state.stream_runtimes[sid]
    with client.stream("GET", f"/api/v1/stream/{sid}/events") as r:
        assert r.status_code == 200
    deadline = time.time() + 5
    while rt._subs and time.time() < deadline:
        time.sleep(0.05)
    assert rt._subs == []


def test_terminal_event_reaches_sse_and_mjpeg(client, rtsp_stub):
    """Both SSE and MJPEG clients observe the terminal transition."""
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None, delay=0.01)
    sid = _start(client)
    _wait_status(client, sid, {"running"})
    saw_terminal = threading.Event()
    video_done = threading.Event()

    def watch_sse():
        with client.stream("GET", f"/api/v1/stream/{sid}/events") as r:
            for line in r.iter_lines():
                if line == "event: terminal":
                    saw_terminal.set()
                    return

    def watch_video():
        with client.stream("GET", f"/api/v1/stream/{sid}/video") as r:
            for _ in r.iter_bytes():
                pass  # ends when the runtime closes the stream
            video_done.set()

    t1 = threading.Thread(target=watch_sse, daemon=True)
    t2 = threading.Thread(target=watch_video, daemon=True)
    t1.start()
    t2.start()
    time.sleep(0.3)  # let both viewers subscribe
    client.post(f"/api/v1/stream/{sid}/stop")
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert saw_terminal.is_set()
    assert video_done.is_set()


def test_concurrent_sse_and_mjpeg_receive_frames(client, rtsp_stub):
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None, delay=0.01)
    sid = _start(client)
    _wait_status(client, sid, {"running"})
    got_sse = threading.Event()
    got_frame = threading.Event()

    def watch_sse():
        with client.stream("GET", f"/api/v1/stream/{sid}/events") as r:
            for line in r.iter_lines():
                if line.startswith("event: frame"):
                    got_sse.set()
                    return

    def watch_video():
        with client.stream("GET", f"/api/v1/stream/{sid}/video") as r:
            for chunk in r.iter_bytes():
                if b"\xff\xd8" in chunk:
                    got_frame.set()
                    return

    t1 = threading.Thread(target=watch_sse, daemon=True)
    t2 = threading.Thread(target=watch_video, daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert got_sse.is_set()
    assert got_frame.is_set()
    client.post(f"/api/v1/stream/{sid}/stop")


def test_viewer_cap_429(client, rtsp_stub):
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None, delay=0.05)
    client.put("/api/v1/setting/max_viewers", json={"value": 1},
               headers={"If-Match": "*"})
    sid = _start(client)
    _wait_status(client, sid, {"running"})
    with client.stream("GET", f"/api/v1/stream/{sid}/video") as r:
        assert r.status_code == 200
        # A second viewer (any surface) is over occupancy.
        assert client.get(f"/api/v1/stream/{sid}/video").status_code == 429
        assert client.get(f"/api/v1/stream/{sid}/events").status_code == 429


def test_snapshot_does_not_consume_viewer_slot(client, rtsp_stub):
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None, delay=0.01)
    client.put("/api/v1/setting/max_viewers", json={"value": 1},
               headers={"If-Match": "*"})
    sid = _start(client)
    _wait_status(client, sid, {"running"})
    deadline = time.time() + 10
    while time.time() < deadline:
        if client.get(f"/api/v1/stream/{sid}").json().get("last_frame_at"):
            break
        time.sleep(0.05)
    assert client.get(f"/api/v1/stream/{sid}/snapshot").status_code == 200
    with client.stream("GET", f"/api/v1/stream/{sid}/video") as r:
        assert r.status_code == 200


def test_jpeg_encoded_once_per_frame(client, rtsp_stub, monkeypatch):
    """Viewers asking for the same frame+variant share one encode."""
    rtsp_stub.stream_factory = lambda: _ClosableFrames(count=None, delay=5.0)
    calls = []
    import opal_look.streams as streams_mod

    real = streams_mod._jpeg

    def counting(img):
        calls.append(1)
        return real(img)

    monkeypatch.setattr(streams_mod, "_jpeg", counting)
    sid = _start(client)
    _wait_status(client, sid, {"running"})
    # wait for the first frame
    deadline = time.time() + 10
    while time.time() < deadline:
        if client.get(f"/api/v1/stream/{sid}").json().get("last_frame_at"):
            break
        time.sleep(0.05)
    snap1 = client.get(f"/api/v1/stream/{sid}/snapshot")
    snap2 = client.get(f"/api/v1/stream/{sid}/snapshot")
    assert snap1.status_code == snap2.status_code == 200
    assert snap1.content == snap2.content
    assert len(calls) == 1  # second snapshot reused the cached encode


@pytest.fixture()
def loaded(client):
    client.post("/api/v1/model/synthetic-det/load")
    yield client
    client.post("/api/v1/model/synthetic-det/unload")

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
        self.open_locators = []

    def open_stream(self, locator, options, credentialed_locator):
        self.open_locators.append(credentialed_locator)
        if self.fail:
            raise self.fail
        return _FakeFrames(count=self.count)


@pytest.fixture()
def rtsp(monkeypatch):
    """Install a fake rtsp capture adapter with an endless frame feed."""
    fake = _FakeRtsp(count=0)
    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp", fake)
    return fake


@pytest.fixture()
def rtsp_frames(monkeypatch):
    fake = _FakeRtsp(count=100)
    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp", fake)
    return fake


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


def test_admission_limit_429(client, fake_rtsp):
    # Endless feed: the occupying stream must stay non-terminal while the
    # second admission is evaluated (a drained stream frees the slot).
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.01
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


def test_named_stream(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]  # endless feed keeps the name held
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "name": "front-door"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["stream_id"] != "front-door"
    assert body["name"] == "front-door"
    assert resp.headers["location"] == \
        f"/api/v1/stream/{body['stream_id']}"
    assert body["events_url"] == \
        f"/api/v1/stream/{body['stream_id']}/events"
    # the name resolves as an alias while the stream holds it
    shown = client.get("/api/v1/stream/front-door").json()
    assert shown["stream_id"] == body["stream_id"]
    assert shown["name"] == "front-door"


def test_named_stream_conflict(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]  # endless feed: stays non-terminal
    fake_rtsp.frame_delay = 0.01
    client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "name": "front-door"})
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/y", "name": "front-door"})
    assert resp.status_code == 409


def test_named_stream_reuse_after_stop(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None, None]
    fake_rtsp.frame_delay = 0.01
    first = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "name": "front-door"}).json()
    assert client.post(
        f"/api/v1/stream/{first['stream_id']}/stop").status_code == 200
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/y", "name": "front-door"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["name"] == "front-door"
    assert body["stream_id"] != first["stream_id"]  # a new run every time
    assert body["source_redacted"] == "rtsp://cam/y"
    # the old run remains addressable by run id; the alias moved on
    old = client.get(f"/api/v1/stream/{first['stream_id']}").json()
    assert old["status"] == "stopped"
    assert client.get("/api/v1/stream/front-door").json()[
        "stream_id"] == body["stream_id"]


def test_name_alias_released_at_terminal(client, rtsp):
    """A terminal stream releases its name alias; the run id still serves
    the stopped status."""
    body = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "name": "gone"}).json()
    _wait(client, body["stream_id"],
          lambda b: b["status"] in ("stopped", "failed"))
    assert client.get("/api/v1/stream/gone").status_code == 404
    assert client.get(
        f"/api/v1/stream/{body['stream_id']}").status_code == 200


def test_named_stream_invalid(client, rtsp_frames):
    for bad in ("has space", "../escape", "-leading", ""):
        resp = client.post("/api/v1/stream/", json={
            "source": "rtsp://cam/x", "name": bad})
        assert resp.status_code == 422, bad


def test_named_stream_idempotent(client, rtsp_frames):
    body = {"source": "rtsp://cam/x", "name": "front-door"}
    a = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-name"})
    b = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-name"})
    assert a.status_code == b.status_code == 202
    assert a.json()["stream_id"] == b.json()["stream_id"]
    assert a.json()["name"] == "front-door"


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


# -- inference mode ----------------------------------------------------------


@pytest.fixture()
def loaded(client):
    client.post("/api/v1/model/synthetic-det/load")
    yield client
    client.post("/api/v1/model/synthetic-det/unload")


def _start_inference(client, **extra):
    return client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "engine_id": "synthetic",
        "model_id": "synthetic-det", **extra})


def test_start_inference_stream(loaded, rtsp_frames):
    resp = _start_inference(loaded)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["mode"] == "inference"
    assert body["engine_id"] == "synthetic"
    assert body["model_id"] == "synthetic-det"
    assert "detections" in body["capabilities"]


def test_inference_requires_loaded_model(client, rtsp_frames):
    client.post("/api/v1/model/synthetic-det/unload")
    assert _start_inference(client).status_code == 409


def test_inference_unknown_engine_model(client, rtsp_frames):
    assert client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "engine_id": "ghost",
        "model_id": "m"}).status_code == 404
    assert client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "engine_id": "synthetic",
        "model_id": "ghost"}).status_code == 404


def test_inference_engine_unavailable_503(loaded, rtsp_frames):
    loaded.patch("/api/v1/engine/synthetic",
                 json={"options": {"force_unavailable": True}},
                 headers={"If-Match": "*"})
    assert _start_inference(loaded).status_code == 503


def test_inference_bad_options_device(loaded, rtsp_frames):
    assert _start_inference(
        loaded, engine_options={"bogus": 1}).status_code == 422
    assert _start_inference(loaded, device_id="gpu-9").status_code == 422


def test_inference_emits_detection_events(loaded, rtsp_frames):
    sid = _start_inference(loaded).json()["stream_id"]
    _wait(loaded, sid, lambda b: (b["frames_processed"] or 0) > 0)
    saw_detection = False
    with loaded.stream("GET", f"/api/v1/stream/{sid}/events") as r:
        for line in r.iter_lines():
            if line.startswith("event: detection"):
                saw_detection = True
                break
    assert saw_detection


def test_inference_metrics_has_latency(loaded, rtsp_frames):
    sid = _start_inference(loaded).json()["stream_id"]
    _wait(loaded, sid, lambda b: (b["frames_processed"] or 0) > 0)
    m = loaded.get(f"/api/v1/stream/{sid}/metrics").json()
    assert m["mode"] == "inference"
    assert m["inference_latency_ms"] is not None


def test_annotated_inference_snapshot(loaded, rtsp_frames):
    sid = _start_inference(loaded, annotate=True).json()["stream_id"]
    _wait(loaded, sid, lambda b: (b["frames_processed"] or 0) > 0)
    resp = loaded.get(f"/api/v1/stream/{sid}/snapshot",
                      params={"annotated": "true"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    # without annotate at admission, annotated view is rejected
    sid2 = _start_inference(loaded).json()["stream_id"]
    assert loaded.get(f"/api/v1/stream/{sid2}/snapshot",
                      params={"annotated": "true"}).status_code == 422


def test_unload_model_in_use_409(loaded, rtsp_frames):
    sid = _start_inference(loaded).json()["stream_id"]
    assert loaded.post("/api/v1/model/synthetic-det/unload").status_code == 409
    loaded.post(f"/api/v1/stream/{sid}/stop")
    assert loaded.post(
        "/api/v1/model/synthetic-det/unload").status_code == 200


def test_credential_ref_injects_locator(client, rtsp, monkeypatch):
    monkeypatch.setenv("OPAL_LOOK_CRED_FRONT", "opallook:helloworld")
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "credential_ref": "front",
        "name": "cred"})
    assert resp.status_code == 202
    sid = resp.json()["stream_id"]
    _wait(client, sid, lambda b: b["status"] != "starting")
    assert rtsp.open_locators == [
        "rtsp://opallook:helloworld@cam/x"]
    shown = client.get(f"/api/v1/stream/{sid}").json()
    assert shown["source_redacted"] == "rtsp://cam/x"


def test_credential_ref_unprovisioned_422(client, rtsp, monkeypatch):
    monkeypatch.delenv("OPAL_LOOK_CRED_MISSING", raising=False)
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "credential_ref": "missing"})
    assert resp.status_code == 422
    assert "OPAL_LOOK_CRED_MISSING" in resp.json()["error"]["message"]


def test_credential_ref_malformed_env_422(client, rtsp, monkeypatch):
    monkeypatch.setenv("OPAL_LOOK_CRED_BROKEN", "no-colon-here")
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/x", "credential_ref": "broken"})
    assert resp.status_code == 422
    assert "user:pass" in resp.json()["error"]["message"]


def test_embedded_userinfo_redacted(client, rtsp):
    resp = client.post("/api/v1/stream/", json={
        "source": "rtsp://u:pw@cam/x", "name": "redact"})
    assert resp.status_code == 202
    sid = resp.json()["stream_id"]
    shown = client.get(f"/api/v1/stream/{sid}").json()
    assert shown["source_redacted"] == "rtsp://cam/x"
    client.post(f"/api/v1/stream/{sid}/stop")


# -- run identity: idempotent retries ------------------------------------------


def test_replay_after_stop_returns_same_run(client, fake_rtsp):
    """A retry after stop returns the recorded run's receipt — it does
    not start a second stream for the spent key."""
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.01
    body = {"source": "rtsp://cam/x", "name": "door"}
    a = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-stop"})
    sid = a.json()["stream_id"]
    client.post(f"/api/v1/stream/{sid}/stop")
    b = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-stop"})
    assert b.status_code == 202
    assert b.json()["stream_id"] == sid
    assert b.json()["status"] == "stopped"


def test_replay_after_name_reuse_binds_old_run(client, fake_rtsp):
    """Name reuse must not rebind the key: replaying the old key returns
    the stopped original run, not the replacement holding the name."""
    fake_rtsp.frames_per_open = [None, None]
    fake_rtsp.frame_delay = 0.01
    body = {"source": "rtsp://cam/x", "name": "door"}
    a = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-old"})
    sid_a = a.json()["stream_id"]
    client.post(f"/api/v1/stream/{sid_a}/stop")
    repl = client.post("/api/v1/stream/", json={
        "source": "rtsp://cam/y", "name": "door"})
    sid_b = repl.json()["stream_id"]
    b = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-old"})
    assert b.status_code == 202
    assert b.json()["stream_id"] == sid_a != sid_b
    assert b.json()["status"] == "stopped"


def test_replay_after_runtime_loss_readmits(client, fake_rtsp):
    """Restart case: the durable key outlives the ephemeral runtime.
    A fingerprint replay re-admits and rebinds to the new run."""
    fake_rtsp.frames_per_open = [None, None]
    fake_rtsp.frame_delay = 0.01
    body = {"source": "rtsp://cam/x"}
    a = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-restart"})
    sid_a = a.json()["stream_id"]
    client.post(f"/api/v1/stream/{sid_a}/stop")
    client.app.state.stream_runtimes.clear()  # simulate process restart
    b = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-restart"})
    assert b.status_code == 202
    sid_b = b.json()["stream_id"]
    assert sid_b != sid_a
    # the key is now bound to the new run
    c = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-restart"})
    assert c.json()["stream_id"] == sid_b


def test_expired_key_readmits_fresh(client, fake_rtsp):
    """After the 24h reservation lapses the same key is a fresh admission,
    not a replay of a spent binding."""
    fake_rtsp.frames_per_open = [None, None]
    fake_rtsp.frame_delay = 0.01
    body = {"source": "rtsp://cam/x"}
    a = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-exp"})
    sid_a = a.json()["stream_id"]
    store = client.app.state.store
    with store.write_txn():
        store._conn.execute(
            "UPDATE idempotency_keys SET expires_at = ? WHERE key = ?",
            ("2000-01-01T00:00:00Z", "k-exp"))
    client.post(f"/api/v1/stream/{sid_a}/stop")
    b = client.post("/api/v1/stream/", json=body,
                    headers={"Idempotency-Key": "k-exp"})
    assert b.status_code == 202
    assert b.json()["stream_id"] != sid_a


def test_concurrent_duplicate_admissions(client, fake_rtsp):
    """N simultaneous same-key requests produce exactly one stream."""
    from concurrent.futures import ThreadPoolExecutor

    fake_rtsp.frames_per_open = [None] * 8
    fake_rtsp.frame_delay = 0.01
    body = {"source": "rtsp://cam/x"}
    headers = {"Idempotency-Key": "k-race"}

    def post():
        return client.post("/api/v1/stream/", json=body, headers=headers)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: post(), range(8)))
    statuses = [r.status_code for r in responses]
    assert all(s == 202 for s in statuses), statuses
    ids = {r.json()["stream_id"] for r in responses}
    assert len(ids) == 1
    runtimes = client.app.state.stream_runtimes
    assert [r for r in runtimes.values()
            if r.status not in ("stopped", "failed")].__len__() == 1


def test_concurrent_same_name_conflict(client, fake_rtsp):
    """N simultaneous same-name admissions produce exactly one holder."""
    from concurrent.futures import ThreadPoolExecutor

    fake_rtsp.frames_per_open = [None] * 8
    fake_rtsp.frame_delay = 0.01
    body = {"source": "rtsp://cam/x", "name": "race-door"}

    def post(i):
        return client.post("/api/v1/stream/", json=body,
                           headers={"Idempotency-Key": f"k-race-{i}"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(post, range(8)))
    statuses = sorted(r.status_code for r in responses)
    assert statuses.count(202) == 1
    assert statuses.count(409) == len(responses) - 1

"""v1.5 operational surfaces: metrics, events status, quota checks."""

from __future__ import annotations


def test_metrics_shape_and_counters(client):
    resp = client.get("/api/v1/metrics/")
    assert resp.status_code == 200
    body = resp.json()
    assert {"captured_frames","processed_frames","dropped_frames",
            "observations_total","event_publish_drops","active_sessions",
            "queued_jobs","mean_inference_ms"} <= set(body)
    assert all(isinstance(v, (int, float)) for v in body.values())


def test_metrics_reflect_work(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}, headers={"If-Match": "*"})
    client.post("/api/v1/monitors/", json={
        "id": "m", "name": "M", "source_id": "cam", "pipeline_id": "p"},
        headers={"If-Match": "*"})
    import time
    deadline = time.time() + 4
    while time.time() < deadline:
        g = client.get("/api/v1/metrics/").json()
        if g["active_source_streams"] >= 1:
            break
        time.sleep(0.05)
    assert g["active_source_streams"] >= 1
    client.delete("/api/v1/monitors/m", headers={"If-Match": "*"})


def test_events_status_disabled_default(client):
    resp = client.get("/api/v1/events/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["transport_status"] == "disabled"
    assert body["drops"] == 0
    assert isinstance(body["topics"], list)


def test_events_status_enabled_unprovisioned(client):
    # events_enabled without a provisioned transport -> PUT is blocked,
    # so force it via settings store directly for this test
    store = client.app.state.store
    store.settings.set("events_enabled", True)
    body = client.get("/api/v1/events/status").json()
    assert body["enabled"] is True
    assert body["transport_status"] == "unprovisioned"


def test_events_status_drops_counter(client):
    store = client.app.state.store
    store.settings.set("events_enabled", True)

    class P:
        n = 0
        def publish(self, t, s, d):
            self.n = getattr(self, "n", 0) + 1
        def stats(self):
            return {"published": self.n, "dropped": 3,
                    "rate_limited": 1, "queue_depth": 0}
        def close(self):
            pass
    client.app.state.event_publisher = P()
    client.app.state.event_transport = "inproc://fake"
    body = client.get("/api/v1/events/status").json()
    assert body["enabled"] is True
    assert body["drops"] == 4  # dropped + rate_limited
    assert body["transport_status"] == "provisioned"


def test_viewer_quota_429(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    client.put("/api/v1/settings/max_viewers",
               json={"value": 1}, headers={"If-Match": "*"})
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    with client.stream("GET", "/api/v1/sources/cam/stream") as r:
        next(r.iter_bytes(), b"")
        resp2 = client.get("/api/v1/sources/cam/stream")
        assert resp2.status_code == 429


def test_monitor_quota_429(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    client.put("/api/v1/settings/max_monitors",
               json={"value": 1}, headers={"If-Match": "*"})
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}, headers={"If-Match": "*"})
    client.post("/api/v1/monitors/", json={
        "id": "m1", "name": "M", "source_id": "cam", "pipeline_id": "p",
        "enabled": False}, headers={"If-Match": "*"})
    assert client.post("/api/v1/monitors/", json={
        "id": "m2", "name": "M", "source_id": "cam", "pipeline_id": "p",
        "enabled": False}, headers={"If-Match": "*"}).status_code == 429


def test_health_surfaces(client):
    for path in ("/", "/health", "/api/v1/health/live", "/api/v1/health/ready"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.status_code)


def test_uploaded_bytes_bound(client):
    import io
    from PIL import Image
    client.put("/api/v1/settings/max_upload_bytes",
               json={"value": 256}, headers={"If-Match": "*"})
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (10, 20, 30)).save(buf, "JPEG")
    r = client.post("/api/v1/media/",
                    files={"file": ("f.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code in (413, 422)


def test_missing_engine_graceful(client):
    resp = client.get("/api/v1/engines/ghost-engine")
    assert resp.status_code in (404, 422)


def test_disconnect_storm_no_unbounded_growth(client, fake_rtsp):
    """Open/close several viewer streams back to back; the app stays
    responsive and the monitor count never leaks."""
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.01
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    for _ in range(5):
        with client.stream("GET", "/api/v1/sources/cam/stream") as r:
            next(r.iter_bytes(), b"")
    g = client.get("/api/v1/metrics/").json()
    assert g["active_source_streams"] <= 1  # disconnects released
    assert client.get("/api/v1/health/ready").status_code == 200

"""v1.5 recordings: explicit start/stop lifecycle, bounded disk, media output."""

from __future__ import annotations

import time


def _setup(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.01
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})


def _wait_state(client, rid, want=("completed", "failed"), timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/api/v1/recordings/{rid}").json()["state"]
        if st in want:
            return st
        time.sleep(0.03)
    return client.get(f"/api/v1/recordings/{rid}").json()["state"]


def test_recording_lifecycle(client, fake_rtsp):
    _setup(client, fake_rtsp)
    resp = client.post("/api/v1/recordings/", json={"source_id": "cam"},
                       headers={"If-Match": "*"})
    assert resp.status_code == 202
    rid = resp.json()["id"]
    assert resp.json()["state"] in ("starting", "recording")
    stop = client.post(f"/api/v1/recordings/{rid}/stop")
    assert stop.status_code == 200
    assert _wait_state(client, rid) == "completed"
    done = client.get(f"/api/v1/recordings/{rid}").json()
    assert done["media_id"]
    # output is decodable MJPEG media
    r = client.get(f"/api/v1/artifacts/{done['artifact_id']}/content")
    assert r.status_code == 200
    assert r.content[:2] == b"\xff\xd8"  # JPEG magic at stream head
    arow = client.get(f"/api/v1/artifacts/{done['artifact_id']}").json()
    assert arow["kind"] == "video" and arow["source_id"] == "cam"


def test_recording_repeated_stop_idempotent(client, fake_rtsp):
    _setup(client, fake_rtsp)
    rid = client.post("/api/v1/recordings/", json={"source_id": "cam"},
                      headers={"If-Match": "*"}).json()["id"]
    client.post(f"/api/v1/recordings/{rid}/stop")
    _wait_state(client, rid)
    done1 = client.get(f"/api/v1/recordings/{rid}").json()
    resp2 = client.post(f"/api/v1/recordings/{rid}/stop")
    assert resp2.status_code == 200
    assert resp2.json()["media_id"] == done1["media_id"]


def test_recording_duration_cap(client, fake_rtsp):
    _setup(client, fake_rtsp)
    rid = client.post("/api/v1/recordings/", json={
        "source_id": "cam", "max_duration_seconds": 1},
        headers={"If-Match": "*"}).json()["id"]
    assert _wait_state(client, rid, ("completed",), timeout=8.0) == "completed"


def test_recording_disk_bound(client, fake_rtsp):
    _setup(client, fake_rtsp)
    client.put("/api/v1/settings/recording_max_bytes",
               json={"value": 2048}, headers={"If-Match": "*"})
    rid = client.post("/api/v1/recordings/", json={"source_id": "cam"},
                      headers={"If-Match": "*"}).json()["id"]
    assert _wait_state(client, rid, ("completed",), timeout=8.0) == "completed"
    aid = client.get(f"/api/v1/recordings/{rid}").json()["artifact_id"]
    r = client.get(f"/api/v1/artifacts/{aid}/content")
    assert len(r.content) <= 2048


def test_recording_include_audio_422(client, fake_rtsp):
    _setup(client, fake_rtsp)
    resp = client.post("/api/v1/recordings/", json={
        "source_id": "cam", "include_audio": True},
        headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_recording_unsupported_output_422(client, fake_rtsp):
    _setup(client, fake_rtsp)
    resp = client.post("/api/v1/recordings/", json={
        "source_id": "cam", "output": {"format": "mp4"}},
        headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_recording_finite_source_422(client):
    client.post("/api/v1/sources/", json={
        "id": "f", "name": "F", "kind": "file", "locator": "/tmp/x.jpg"},
        headers={"If-Match": "*"})
    resp = client.post("/api/v1/recordings/", json={"source_id": "f"},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_recording_unknown_source_404(client):
    assert client.post("/api/v1/recordings/", json={"source_id": "ghost"},
                       headers={"If-Match": "*"}).status_code == 404


def test_recording_unknown_id_404(client):
    assert client.get("/api/v1/recordings/ghost").status_code == 404
    assert client.post("/api/v1/recordings/ghost/stop").status_code == 404


def test_source_delete_blocked_by_active_recording(client, fake_rtsp):
    _setup(client, fake_rtsp)
    rid = client.post("/api/v1/recordings/", json={"source_id": "cam"},
                      headers={"If-Match": "*"}).json()["id"]
    resp = client.delete("/api/v1/sources/cam", headers={"If-Match": "*"})
    assert resp.status_code == 409
    client.post(f"/api/v1/recordings/{rid}/stop")
    _wait_state(client, rid)
    assert client.delete("/api/v1/sources/cam",
                         headers={"If-Match": "*"}).status_code == 204


def test_recording_viewing_independence(client, fake_rtsp):
    """A viewer stream must never create or stop a recording."""
    _setup(client, fake_rtsp)
    with client.stream("GET", "/api/v1/sources/cam/stream") as r:
        next(r.iter_bytes(), b"")
    assert client.get("/api/v1/recordings/").json()["items"] == []


def test_recording_interrupted_on_restart(tmp_path):
    from fastapi.testclient import TestClient
    from opal_look.app import create_app
    c = TestClient(create_app(data_dir=str(tmp_path)))
    c.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    store = c.app.state.store
    store.recordings.insert({
        "recording_id": "rec-x", "source_id": "cam", "state": "recording",
        "created_at": "2025-01-01T00:00:00Z"})
    c2 = TestClient(create_app(data_dir=str(tmp_path)))
    rec = c2.get("/api/v1/recordings/rec-x").json()
    assert rec["state"] == "failed"
    assert rec["failure"]["code"] == "interrupted"
    assert rec["media_id"] is None

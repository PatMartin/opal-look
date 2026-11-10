"""Upstream Session resource: start/list/show/stop/observations/stream/preview."""

import io
import time

from PIL import Image

PIPE = {"id": "p1", "name": "P", "stages": [
    {"id": "s1", "kind": "inference",
     "model_id": "synthetic-vision", "task": "detection"}]}


def _media_source(client, tmp_path):
    path = tmp_path / "still.png"
    Image.new("RGB", (8, 8), (200, 10, 10)).save(path, format="PNG")
    up = client.post("/api/v1/media/",
                     files={"file": ("x.png", path.read_bytes(), "image/png")})
    mid = up.json().get("id") or up.json()["media_id"]
    client.post("/api/v1/source/", json={
        "id": "ms", "name": "M", "kind": "media", "locator": mid},
        headers={"If-Match": "*"})
    client.post("/api/v1/pipeline/", json=PIPE, headers={"If-Match": "*"})
    return mid


def test_start_and_terminal_state(client, tmp_path):
    _media_source(client, tmp_path)
    resp = client.post("/api/v1/session/", json={
        "source_id": "ms", "pipeline_id": "p1"}, headers={"If-Match": "*"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"].startswith("session-")
    assert body["pipeline_id"] == "p1"
    assert body["source_id"] == "ms"
    # media source completes quickly — worker processes one frame then ends
    for _ in range(50):
        row = client.get(f"/api/v1/session/{body['id']}").json()
        if row["state"] in ("completed", "stopped", "failed"):
            break
        time.sleep(0.1)
    assert row["state"] == "completed", row
    assert row["ended_at"]
    # v1.7.1: the session-scoped observations route was retired;
    # observations stay queryable via /api/v1/observation/
    obs = client.get("/api/v1/observation/")
    assert obs.status_code == 200


def test_queued_auto_start_false(client, tmp_path):
    _media_source(client, tmp_path)
    resp = client.post("/api/v1/session/", json={
        "source_id": "ms", "pipeline_id": "p1", "auto_start": False})
    assert resp.status_code == 201
    assert resp.json()["state"] == "queued"
    sid = resp.json()["id"]
    stop = client.post(f"/api/v1/session/{sid}/stop")
    assert stop.status_code == 200
    assert stop.json()["state"] == "stopped"


def test_default_pipeline_resolution(client, tmp_path):
    _media_source(client, tmp_path)
    client.put("/api/v1/setting/default_pipeline_id",
               json={"value": "p1"}, headers={"If-Match": "*"})
    resp = client.post("/api/v1/session/", json={"source_id": "ms"})
    assert resp.status_code == 201
    assert resp.json()["pipeline_id"] == "p1"


def test_unknown_refs(client, tmp_path):
    _media_source(client, tmp_path)
    assert client.post("/api/v1/session/", json={
        "source_id": "ghost"}).status_code == 404
    assert client.post("/api/v1/session/", json={
        "source_id": "ms", "pipeline_id": "ghost"}).status_code == 404
    assert client.post("/api/v1/session/", json={
        "source_id": "ms", "profile_id": 999}).status_code == 404
    # no pipeline resolvable -> 422
    assert client.post("/api/v1/session/", json={
        "source_id": "ms"}).status_code in (404, 422)


def test_stop_terminal_409(client, tmp_path):
    _media_source(client, tmp_path)
    resp = client.post("/api/v1/session/", json={
        "source_id": "ms", "pipeline_id": "p1", "auto_start": False})
    sid = resp.json()["id"]
    client.post(f"/api/v1/session/{sid}/stop")
    assert client.post(f"/api/v1/session/{sid}/stop").status_code == 409


def test_stream_and_preview_respond(client, tmp_path):
    _media_source(client, tmp_path)
    sid = client.post("/api/v1/session/", json={
        "source_id": "ms", "pipeline_id": "p1"}).json()["id"]
    with client.stream("GET", f"/api/v1/session/{sid}/stream") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        chunk = next(r.iter_text(), "")
        assert chunk.startswith(":")
    with client.stream("GET", f"/api/v1/session/{sid}/preview") as r:
        assert r.status_code == 200
        assert "multipart" in r.headers["content-type"]


def test_list_sessions(client, tmp_path):
    _media_source(client, tmp_path)
    client.post("/api/v1/session/", json={
        "source_id": "ms", "pipeline_id": "p1", "auto_start": False})
    rows = client.get("/api/v1/session/").json()
    assert len(rows) == 1 and rows[0]["state"] == "queued"

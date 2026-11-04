"""v1.5 POST /api/v1/analyze/: SourceInput + pipeline resolution + response."""

from __future__ import annotations

import io

from PIL import Image

SIMPLE = {"id": "p", "name": "P", "model_id": "synthetic-vision", "task": "detection"}


def _media(client, color=(10, 20, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="JPEG")
    return client.post("/api/v1/media/",
                       files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")}
                       ).json()["id"]


def _pipeline(client, pid="p", **over):
    body = {"id": pid, "name": "P", **over}
    if "model_id" not in over and "stages" not in over:
        body.update(model_id="synthetic-vision", task="detection")
    return client.post("/api/v1/pipelines/", json=body, headers={"If-Match": "*"})


def test_media_still_detections(client):
    _pipeline(client)
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid}})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) <= {"observations", "processing_ms", "media_id"}
    obs = body["observations"][0]
    assert obs["pipeline_id"] == "p"
    assert obs["pipeline_revision"] == "1"
    assert obs["media_id"] == mid
    assert obs["task"] == "detection"
    assert obs["transaction_id"] and obs["request_id"]
    assert obs["items"]
    for it in obs["items"]:
        assert it["type"] == "detection"
        box = it["box"]
        assert 0 <= box["x"] <= 1 and 0 <= box["width"] <= 1  # normalized


def test_source_current_frame(client, fake_rtsp):
    _pipeline(client)
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp",
        "locator": "rtsp://192.168.1.5/x"}, headers={"If-Match": "*"})
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"source_id": "cam"}})
    assert resp.status_code == 200
    assert resp.json()["observations"][0]["source_id"] == "cam"
    assert fake_rtsp.grab_calls


def test_mixed_input_422(client):
    _pipeline(client)
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"source_id": "s", "media_id": mid}})
    assert resp.status_code == 422


def test_neither_input_422(client):
    _pipeline(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {}})
    assert resp.status_code == 422


def test_unknown_pipeline_404(client):
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "ghost", "source": {"media_id": mid}})
    assert resp.status_code == 404


def test_missing_pipeline_and_default_422(client):
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={"source": {"media_id": mid}})
    assert resp.status_code == 422


def test_default_pipeline_resolves(client):
    _pipeline(client)
    client.put("/api/v1/settings/default_pipeline_id",
               json={"value": "p"}, headers={"If-Match": "*"})
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={"source": {"media_id": mid}})
    assert resp.status_code == 200
    assert resp.json()["observations"][0]["pipeline_id"] == "p"


def test_unknown_media_404(client):
    _pipeline(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": "ghost"}})
    assert resp.status_code == 404


def test_unknown_source_404(client):
    _pipeline(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"source_id": "ghost"}})
    assert resp.status_code == 404


def test_unavailable_source_503(client, fake_rtsp):
    _pipeline(client)
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "enabled": False,
        "locator": "rtsp://x"}, headers={"If-Match": "*"})
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"source_id": "cam"}})
    assert resp.status_code == 503


def test_frame_at_ms_422(client):
    _pipeline(client)
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid, "frame_at_ms": 100}})
    assert resp.status_code == 422


def test_options_confidence_filter(client):
    _pipeline(client)
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid},
        "options": {"confidence_threshold": 0.999}})
    assert resp.status_code == 200
    assert resp.json()["observations"][0]["items"] == []


def test_options_classes_filter(client):
    _pipeline(client)
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid},
        "options": {"classes": ["definitely-not-a-label"]}})
    assert resp.status_code == 200
    assert resp.json()["observations"][0]["items"] == []


def test_no_default_retention(client):
    """One-shot analyze persists nothing by default."""
    _pipeline(client)
    mid = _media(client)
    before_media = len(client.get("/api/v1/media/").json()["items"])
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid}})
    assert resp.status_code == 200
    assert resp.json()["media_id"] is None
    # nothing retained: no new media rows, no public session
    assert len(client.get("/api/v1/media/").json()["items"]) == before_media


def test_retention_save_raw_frames(client):
    _pipeline(client)
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid},
        "retention": {"save_raw_frames": True}})
    assert resp.status_code == 200
    out_mid = resp.json()["media_id"]
    assert out_mid and out_mid.startswith("media-")
    got = client.get(f"/api/v1/media/{out_mid}").json()
    assert got["id"] == out_mid


def test_retention_ttl_over_cap_422(client):
    _pipeline(client)
    mid = _media(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid},
        "retention": {"ttl_seconds": 10**12}})
    assert resp.status_code == 422


def test_no_public_session_created(client):
    _pipeline(client)
    mid = _media(client)
    client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid}})
    # sessions list should have no rows for this source/media
    page = client.get("/api/v1/sessions/").json()
    assert page.get("items", page) in ([], page) or not page.get("items")

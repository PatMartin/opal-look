"""Upstream /analyze/: SourceInput + pipeline -> AnalyzeResponse."""

import io
import time

import pytest
from PIL import Image


def _img(fmt="JPEG", size=(48, 36), color=(10, 120, 220)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def _pipeline(client, task="detection", pid="p"):
    client.post("/api/v1/pipeline/", json={
        "id": pid, "name": "P", "stages": [
            {"id": "s1", "kind": "inference",
             "model_id": "synthetic-vision", "task": task}]},
        headers={"If-Match": "*"})


@pytest.fixture()
def media_id(client):
    resp = client.post(
        "/api/v1/media/", files={"file": ("pic.jpg", _img(), "image/jpeg")})
    assert resp.status_code == 201
    return resp.json()["id"]


def _analyze(client, media_id, **overrides):
    body = {"source": {"media_id": media_id}, "pipeline_id": "p"}
    body.update(overrides)
    return client.post("/api/v1/analyze", json=body)


def test_analyze_detection(client, media_id):
    _pipeline(client)
    resp = _analyze(client, media_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image"]["width"] == 48 and body["image"]["height"] == 36
    assert body["processing_ms"] >= 0
    assert body["observations"]
    det = next(o for o in body["observations"] if o["task"] == "detection")
    assert det["items"]
    for it in det["items"]:
        assert it["label"] and 0 <= it["score"] <= 1


def test_analyze_pipeline_required(client, media_id):
    resp = client.post("/api/v1/analyze",
                       json={"source": {"media_id": media_id}})
    assert resp.status_code == 422  # no pipeline_id, no default configured


def test_analyze_default_pipeline(client, media_id):
    _pipeline(client)
    client.put("/api/v1/setting/default_pipeline_id",
               json={"value": "p"}, headers={"If-Match": "*"})
    resp = client.post("/api/v1/analyze",
                       json={"source": {"media_id": media_id}})
    assert resp.status_code == 200


def test_analyze_via_profile(client, media_id):
    _pipeline(client)
    client.post("/api/v1/profile/", json={
        "name": "p", "pipeline_id": "p", "is_active": False},
        headers={"If-Match": "*"})
    pid = client.get("/api/v1/profile/").json()[0]["id"]
    resp = client.post("/api/v1/analyze", json={
        "source": {"media_id": media_id}, "profile_id": str(pid)})
    assert resp.status_code == 200
    assert resp.json()["observations"][0]["task"] == "detection"


def test_analyze_persisted_result(client, media_id):
    _pipeline(client)
    body = _analyze(
        client, media_id,
        retention={"persist_results": True}).json()
    obs = client.get("/api/v1/observation/").json()["items"]
    assert obs, "persist_results should store observations"


def test_analyze_unknown_refs(client, media_id):
    _pipeline(client)
    assert _analyze(client, media_id, pipeline_id="ghost").status_code == 404
    resp = client.post("/api/v1/analyze", json={
        "source": {"media_id": "ghost"}, "pipeline_id": "p"})
    assert resp.status_code == 404
    resp = client.post("/api/v1/analyze", json={
        "source": {"media_id": media_id}, "profile_id": "999"})
    assert resp.status_code == 404


def test_analyze_expired_media_410(client, media_id):
    _pipeline(client)
    client.delete(f"/api/v1/media/{media_id}", headers={"If-Match": "*"})
    resp = _analyze(client, media_id)
    assert resp.status_code in (404, 410)


def test_analyze_one_source_input_required(client, media_id):
    _pipeline(client)
    resp = client.post("/api/v1/analyze", json={
        "source": {"media_id": media_id, "source_id": "x"},
        "pipeline_id": "p"})
    assert resp.status_code == 422
    resp = client.post("/api/v1/analyze", json={
        "source": {}, "pipeline_id": "p"})
    assert resp.status_code == 422


def test_analyze_capture_input(client, media_id, tmp_path):
    _pipeline(client)
    path = tmp_path / "f.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(path, format="PNG")
    up = client.post("/api/v1/media/",
                     files={"file": ("f.png", path.read_bytes(), "image/png")})
    mid = up.json()["id"]
    client.post("/api/v1/source/", json={
        "id": "ms", "name": "M", "kind": "media", "locator": mid},
        headers={"If-Match": "*"})
    cap = client.post("/api/v1/source/ms/capture/",
                      json={"retain": True}, headers={"If-Match": "*"}).json()
    resp = client.post("/api/v1/analyze", json={
        "source": {"capture_id": cap["id"]}, "pipeline_id": "p"})
    assert resp.status_code == 200


def test_analyze_rtsp_source(client, media_id, fake_rtsp):
    _pipeline(client)
    fake_rtsp.frames_per_open = [None]
    client.post("/api/v1/source/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    resp = client.post("/api/v1/analyze", json={
        "source": {"source_id": "cam"}, "pipeline_id": "p"})
    assert resp.status_code == 200


def test_analyze_image_multipart(client):
    _pipeline(client)
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("x.jpg", _img(), "image/jpeg")},
        data={"request": '{"pipeline_id": "p"}'})
    assert resp.status_code == 200
    assert resp.json()["observations"]


def test_analyze_confidence_filter(client, media_id):
    _pipeline(client)
    low = _analyze(client, media_id,
                   options={"confidence_threshold": 0.0}).json()
    high = _analyze(client, media_id,
                    options={"confidence_threshold": 0.99}).json()
    lo = sum(len(o["items"]) for o in low["observations"])
    hi = sum(len(o["items"]) for o in high["observations"])
    assert hi <= lo

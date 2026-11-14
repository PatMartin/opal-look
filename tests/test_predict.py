import io

import pytest
from PIL import Image


@pytest.fixture()
def image_path(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 20, 30)).save(buf, format="JPEG")
    p = tmp_path / "img.jpg"
    p.write_bytes(buf.getvalue())
    return str(p)


@pytest.fixture()
def loaded(client):
    client.post("/api/v1/model/synthetic-det/load")
    yield client
    client.post("/api/v1/model/synthetic-det/unload")


def test_predict_happy(loaded, image_path):
    resp = loaded.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": image_path})
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine_id"] == "synthetic"
    assert body["model_id"] == "synthetic-det"
    assert body["image"] == {"width": 64, "height": 48}
    assert isinstance(body["detections"], list)
    for d in body["detections"]:
        assert set(d) == {"class_id", "class_name", "confidence", "box"}
        assert len(d["box"]) == 4
        assert 0 <= d["confidence"] <= 1
    assert body["execution_id"]
    assert "native" not in body


def test_predict_include_native(loaded, image_path):
    resp = loaded.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": image_path, "include_native": True})
    assert resp.status_code == 200
    assert resp.json()["native"]["adapter"] == "synthetic"


def test_predict_confidence_filter(loaded, image_path):
    resp = loaded.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": image_path, "confidence": 1.0})
    assert resp.status_code == 200
    assert resp.json()["detections"] == []


def test_predict_requires_loaded_model(client, image_path):
    client.post("/api/v1/model/synthetic-det/unload")
    resp = client.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": image_path})
    assert resp.status_code == 409


def test_predict_unknown_engine_model(client, image_path):
    resp = client.post("/api/v1/predict", json={
        "engine_id": "ghost", "model_id": "synthetic-det",
        "source": image_path})
    assert resp.status_code == 404
    resp = client.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "ghost",
        "source": image_path})
    assert resp.status_code == 404


def test_predict_bad_engine_options(loaded, image_path):
    resp = loaded.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": image_path, "engine_options": {"bogus": 1}})
    assert resp.status_code == 422


def test_predict_bad_device(loaded, image_path):
    resp = loaded.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": image_path, "device_id": "gpu-9"})
    assert resp.status_code == 422


def test_predict_missing_source(loaded):
    resp = loaded.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": "/no/such/file.jpg"})
    assert resp.status_code == 422


def test_predict_not_an_image(loaded, tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"not an image")
    resp = loaded.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": str(p)})
    assert resp.status_code == 422


def test_predict_engine_unavailable(loaded, image_path):
    loaded.patch("/api/v1/engine/synthetic",
                 json={"options": {"force_unavailable": True}},
                 headers={"If-Match": "*"})
    resp = loaded.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": image_path})
    assert resp.status_code == 503


def test_predict_deterministic_with_seed(loaded, image_path):
    body = {"engine_id": "synthetic", "model_id": "synthetic-det",
            "source": image_path, "engine_options": {"seed": 7}}
    a = loaded.post("/api/v1/predict", json=body).json()
    b = loaded.post("/api/v1/predict", json=body).json()
    assert a["detections"] == b["detections"]

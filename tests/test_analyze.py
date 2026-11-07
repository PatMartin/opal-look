import io

import pytest
from PIL import Image


def _img(fmt="JPEG", size=(48, 36), color=(10, 120, 220)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture()
def media_id(client):
    resp = client.post(
        "/api/v1/media/", files={"file": ("pic.jpg", _img(), "image/jpeg")}
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _analyze(client, media_id, **overrides):
    body = {
        "input": {"kind": "media", "media_id": media_id},
        "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}],
    }
    body.update(overrides)
    return client.post("/api/v1/analyze", json=body)


def test_analyze_detection(client, media_id):
    resp = _analyze(client, media_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["task"] == "detection"
    assert body["payload"]["task"] == "detection"
    assert body["frame_index"] == 0
    assert body["session_id"] is None
    assert body["media_id"] == media_id
    assert body["width"] == 48 and body["height"] == 36
    assert body["stored"] is True
    assert body["expires_at"] > body["analyzed_at"]
    for obj in body["payload"]["objects"]:
        assert obj["track_id"] is None
        box = obj["box"]
        assert 0 <= box["x"] <= 1 and 0 < box["width"] <= 1


@pytest.mark.parametrize("task", ["classification", "pose", "ocr"])
def test_analyze_other_tasks(client, media_id, task):
    resp = _analyze(client, media_id, task=task)
    assert resp.status_code == 200
    assert resp.json()["payload"]["task"] == task


def test_analyze_segmentation_instance(client, media_id):
    resp = _analyze(
        client, media_id, task="segmentation",
        settings={"segmentation_kind": "instance"},
    )
    assert resp.status_code == 200
    payload = resp.json()["payload"]
    assert payload["kind"] == "instance"
    for inst in payload["instances"]:
        mask = inst["mask"]
        assert mask["encoding"] == "rle"
        assert sum(mask["counts"]) == mask["width"] * mask["height"]


def test_analyze_segmentation_semantic(client, media_id):
    resp = _analyze(
        client, media_id, task="segmentation",
        settings={"segmentation_kind": "semantic"},
    )
    assert resp.status_code == 200
    m = resp.json()["payload"]["map"]
    assert sum(r["count"] for r in m["runs"]) == m["width"] * m["height"]


def test_analyze_stored_result_persisted(client, media_id):
    body = _analyze(client, media_id).json()
    row = client.app.state.store.results.get(body["result_id"])
    assert row is not None


def test_analyze_store_result_false(client, media_id):
    resp = _analyze(client, media_id, store_result=False)
    assert resp.status_code == 200
    body = resp.json()
    assert body["stored"] is False
    assert body["expires_at"] is None
    assert client.app.state.store.results.get(body["result_id"]) is None


def test_analyze_via_profile(client, media_id):
    prof = client.post(
        "/api/v1/profiles/",
        json={"name": "p", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "ocr"}]},
        headers={"If-Match": "*"},
    ).json()
    resp = client.post(
        "/api/v1/analyze",
        json={"input": {"kind": "media", "media_id": media_id}},
    )
    # Active profile resolves model+task.
    assert resp.status_code == 200
    assert resp.json()["task"] == "ocr"

    resp = client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "media", "media_id": media_id},
            "profile_id": prof["profile_id"],
            "task": "classification",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["task"] == "classification"


def test_analyze_no_model_no_profile_422(client, media_id):
    resp = client.post(
        "/api/v1/analyze", json={"input": {"kind": "media", "media_id": media_id}}
    )
    assert resp.status_code == 422


def test_analyze_unknown_media_404(client):
    resp = client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "media", "media_id": "ghost"},
            "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}],
        },
    )
    assert resp.status_code == 404


def test_analyze_expired_media_410(client, media_id):
    store = client.app.state.store
    store._conn.execute(
        "UPDATE media SET expires_at = '2000-01-01T00:00:00Z' WHERE media_id = ?",
        (media_id,),
    )
    assert _analyze(client, media_id).status_code == 410


def test_analyze_unknown_model_404(client, media_id):
    resp = _analyze(client, media_id, model_id="ghost")
    assert resp.status_code == 404


def test_analyze_engine_disabled_503(client, media_id):
    client.patch(
        "/api/v1/engines/synthetic", json={"enabled": False}, headers={"If-Match": "*"}
    )
    resp = _analyze(client, media_id)
    assert resp.status_code == 503


def test_analyze_engine_unavailable_503(client, media_id):
    client.patch(
        "/api/v1/engines/synthetic",
        json={"options": {"force_unavailable": True}},
        headers={"If-Match": "*"},
    )
    resp = _analyze(client, media_id)
    assert resp.status_code == 503


def test_analyze_tracking_422(client, media_id):
    resp = _analyze(client, media_id, settings={"tracking": True})
    assert resp.status_code == 422


def test_analyze_engine_fail_503(client, media_id):
    resp = _analyze(client, media_id, settings={"engine_options": {"fail": True}})
    assert resp.status_code == 503


def test_analyze_confidence_filter(client, media_id):
    low = _analyze(client, media_id, settings={"confidence": 0.0}).json()
    high = _analyze(client, media_id, settings={"confidence": 0.99}).json()
    assert len(high["payload"]["objects"]) <= len(low["payload"]["objects"])


def test_analyze_class_label_filter(client, media_id):
    resp = _analyze(client, media_id, settings={"class_labels": ["person"]})
    for obj in resp.json()["payload"]["objects"]:
        assert obj["label"] == "person"


def test_analyze_unknown_source_404(client):
    resp = client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "source", "source_id": "ghost"},
            "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}],
        },
    )
    assert resp.status_code == 404


def test_analyze_media_backed_source(client, media_id):
    client.post(
        "/api/v1/sources/",
        json={"id": "ms", "name": "M", "kind": "media", "locator": media_id},
        headers={"If-Match": "*"},
    )
    resp = client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "source", "source_id": "ms"},
            "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["source_id"] == "ms"
    assert resp.json()["media_id"] == media_id


def test_analyze_position_ms_on_media_image_422(client, media_id):
    client.post(
        "/api/v1/sources/",
        json={"id": "ms", "name": "M", "kind": "media", "locator": media_id},
        headers={"If-Match": "*"},
    )
    resp = client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "source", "source_id": "ms", "position_ms": 5},
            "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}],
        },
    )
    assert resp.status_code == 422


def test_analyze_unavailable_source_503(client):
    client.post(
        "/api/v1/sources/",
        json={
            "id": "cam", "name": "Cam", "kind": "rtsp",
            "locator": "rtsp://192.0.2.1/feed",
            "enabled": False,
        },
        headers={"If-Match": "*"},
    )
    resp = client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "source", "source_id": "cam"},
            "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}],
        },
    )
    assert resp.status_code == 503


def test_analyze_deterministic_with_seed(client, media_id):
    a = _analyze(client, media_id, settings={"engine_options": {"seed": 42}}).json()
    b = _analyze(client, media_id, settings={"engine_options": {"seed": 42}}).json()
    assert a["payload"] == b["payload"]


def _rtsp_source(client, source_id="cam"):
    client.post(
        "/api/v1/sources/",
        json={
            "id": source_id, "name": "Cam", "kind": "rtsp",
            "locator": "rtsp://192.0.2.1/feed",
        },
        headers={"If-Match": "*"},
    )


def _analyze_source(client, source_id="cam", **overrides):
    body = {
        "input": {"kind": "source", "source_id": source_id},
        "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}],
    }
    body.update(overrides)
    return client.post("/api/v1/analyze", json=body)


def test_analyze_rtsp_source(client, fake_rtsp):
    _rtsp_source(client)
    resp = _analyze_source(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_id"] == "cam"
    assert body["media_id"] is None
    assert body["position_ms"] is None
    assert body["width"] == 16 and body["height"] == 16
    assert body["payload"]["task"] == "detection"
    assert fake_rtsp.grab_calls == ["rtsp://192.0.2.1/feed"]


def test_analyze_rtsp_grab_failure_503(client, fake_rtsp):
    from opal_look.capture import CaptureError

    fake_rtsp.grab_error = CaptureError("connect timeout")
    _rtsp_source(client)
    resp = _analyze_source(client)
    assert resp.status_code == 503


def test_analyze_rtsp_position_ms_422(client, fake_rtsp):
    _rtsp_source(client)
    resp = _analyze_source(
        client, input={"kind": "source", "source_id": "cam", "position_ms": 5})
    assert resp.status_code == 422


def test_analyze_rtsp_unresolved_credential_503(client, fake_rtsp, monkeypatch):
    monkeypatch.delenv("OPAL_LOOK_CRED_DRIVEWAY", raising=False)
    client.post(
        "/api/v1/sources/",
        json={
            "id": "cam", "name": "Cam", "kind": "rtsp",
            "locator": "rtsp://192.0.2.1/feed", "secret_ref": "driveway",
        },
        headers={"If-Match": "*"},
    )
    resp = _analyze_source(client)
    assert resp.status_code == 503

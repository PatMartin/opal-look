import pytest

BASE = {
    "name": "Detect people",
    "model_id": "synthetic-vision",
    "task": "detection",
}


def _create(client, **overrides):
    body = {**BASE, **overrides}
    return client.post("/api/v1/profiles/", json=body, headers={"If-Match": "*"})


def test_create_first_profile_auto_active(client):
    resp = _create(client)
    assert resp.status_code == 201
    assert resp.headers["location"].startswith("/api/v1/profiles/")
    body = resp.json()
    assert body["active"] is True
    assert body["profile_id"] >= 1
    # Resolved defaults are materialized.
    assert body["settings"]["confidence"] == 0.25
    assert body["settings"]["max_fps"] == 5
    # Irrelevant control omitted for non-segmentation task.
    assert "segmentation_kind" not in body["settings"]


def test_second_profile_not_active_and_activation(client):
    first = _create(client).json()["profile_id"]
    second = _create(client, name="Other").json()["profile_id"]
    profiles = client.get("/api/v1/profiles/").json()
    assert {p["profile_id"]: p["active"] for p in profiles} == {first: True, second: False}

    resp = client.post(f"/api/v1/profiles/{second}/activate", headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["active"] is True
    profiles = {p["profile_id"]: p["active"] for p in client.get("/api/v1/profiles/").json()}
    assert profiles == {first: False, second: True}


def test_create_profile_requires_if_match(client):
    resp = client.post("/api/v1/profiles/", json=BASE)
    assert resp.status_code == 428


def test_create_unknown_model_404(client):
    resp = _create(client, model_id="ghost")
    assert resp.status_code == 404


def test_create_profile_for_unavailable_model_201(client):
    # v1.5 has no model.enabled; engine-unavailable is a warning, not an error.
    client.patch(
        "/api/v1/engines/synthetic", json={"enabled": False}, headers={"If-Match": "*"}
    )
    resp = _create(client)
    assert resp.status_code == 201


def test_tracking_on_ocr_422(client):
    resp = _create(client, task="ocr", settings={"tracking": True})
    assert resp.status_code == 422


def test_tracking_on_detection_ok(client):
    resp = _create(client, settings={"tracking": True})
    assert resp.status_code == 201
    assert resp.json()["settings"]["tracking"] is True


def test_unknown_class_label_422(client):
    resp = _create(client, settings={"class_labels": ["giraffe"]})
    assert resp.status_code == 422


def test_known_class_label_ok(client):
    resp = _create(client, settings={"class_labels": ["person", "car"]})
    assert resp.status_code == 201
    assert resp.json()["settings"]["class_labels"] == ["person", "car"]


def test_class_labels_on_ocr_422(client):
    resp = _create(client, task="ocr", settings={"class_labels": ["person"]})
    assert resp.status_code == 422


def test_segmentation_kind_on_detection_422(client):
    resp = _create(client, settings={"segmentation_kind": "semantic"})
    assert resp.status_code == 422


def test_segmentation_profile_includes_kind(client):
    resp = _create(client, task="segmentation", settings={"segmentation_kind": "semantic"})
    assert resp.status_code == 201
    assert resp.json()["settings"]["segmentation_kind"] == "semantic"


def test_unknown_engine_option_422(client):
    resp = _create(client, settings={"engine_options": {"bogus": 1}})
    assert resp.status_code == 422


def test_valid_engine_option_ok(client):
    resp = _create(client, settings={"engine_options": {"seed": 7, "latency_ms": 0}})
    assert resp.status_code == 201


def test_get_profile(client):
    pid = _create(client).json()["profile_id"]
    resp = client.get(f"/api/v1/profiles/{pid}")
    assert resp.status_code == 200
    assert resp.json()["profile_id"] == pid
    assert resp.headers["etag"].startswith('"')


def test_get_unknown_profile_404(client):
    assert client.get("/api/v1/profiles/99").status_code == 404


def test_patch_profile(client):
    pid = _create(client).json()["profile_id"]
    resp = client.patch(
        f"/api/v1/profiles/{pid}",
        json={"name": "Renamed", "settings": {"confidence": 0.9}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["settings"]["confidence"] == 0.9


def test_patch_profile_requires_if_match(client):
    pid = _create(client).json()["profile_id"]
    resp = client.patch(f"/api/v1/profiles/{pid}", json={"name": "x"})
    assert resp.status_code == 428


def test_patch_unknown_profile_404(client):
    resp = client.patch("/api/v1/profiles/99", json={"name": "x"}, headers={"If-Match": "*"})
    assert resp.status_code == 404


def test_patch_incompatible_settings_422(client):
    pid = _create(client).json()["profile_id"]
    resp = client.patch(
        f"/api/v1/profiles/{pid}", json={"task": "ocr", "settings": {"tracking": True}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_delete_active_profile_409(client):
    pid = _create(client).json()["profile_id"]
    resp = client.delete(f"/api/v1/profiles/{pid}", headers={"If-Match": "*"})
    assert resp.status_code == 409


def test_delete_inactive_profile(client):
    first = _create(client).json()["profile_id"]
    second = _create(client, name="Other").json()["profile_id"]
    resp = client.delete(f"/api/v1/profiles/{second}", headers={"If-Match": "*"})
    assert resp.status_code == 204
    assert resp.headers["etag"].startswith('"')
    assert client.get(f"/api/v1/profiles/{second}").status_code == 404


def test_profile_validate_ok(client):
    pid = _create(client).json()["profile_id"]
    resp = client.post(f"/api/v1/profiles/{pid}/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True


def test_profile_validate_unavailable_model_warns(client):
    pid = _create(client).json()["profile_id"]
    client.patch(
        "/api/v1/engines/synthetic",
        json={"options": {"force_unavailable": True}},
        headers={"If-Match": "*"},
    )
    resp = client.post(f"/api/v1/profiles/{pid}/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert any("unavailable" in w for w in body["warnings"])


def test_profile_validate_disabled_engine_warns(client):
    pid = _create(client).json()["profile_id"]
    client.patch(
        "/api/v1/engines/synthetic", json={"enabled": False}, headers={"If-Match": "*"}
    )
    resp = client.post(f"/api/v1/profiles/{pid}/validate")
    body = resp.json()
    assert body["valid"] is True
    assert any("unavailable" in w for w in body["warnings"])


def test_activate_requires_if_match(client):
    pid = _create(client).json()["profile_id"]
    resp = client.post(f"/api/v1/profiles/{pid}/activate")
    assert resp.status_code == 428


def test_activate_allowed_when_model_unavailable(client):
    first = _create(client).json()["profile_id"]
    second = _create(client, name="Other").json()["profile_id"]
    client.patch(
        "/api/v1/engines/synthetic", json={"enabled": False}, headers={"If-Match": "*"}
    )
    resp = client.post(f"/api/v1/profiles/{second}/activate", headers={"If-Match": "*"})
    assert resp.status_code == 200

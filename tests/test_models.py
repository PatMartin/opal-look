NEW_MODEL = {
    "model_id": "test-model",
    "name": "Test model",
    "engine_id": "synthetic",
    "resource": {"path": "/opt/models/test.bin"},
    "enabled": True,
}


def test_list_models_includes_seed(client):
    resp = client.get("/api/v1/models/")
    assert resp.status_code == 200
    assert resp.headers["etag"].startswith('"')
    ids = [m["model_id"] for m in resp.json()]
    assert "synthetic-vision" in ids


def test_list_models_filters(client):
    assert client.get("/api/v1/models/", params={"engine_id": "synthetic"}).json()
    assert client.get("/api/v1/models/", params={"engine_id": "other"}).json() == []
    assert client.get("/api/v1/models/", params={"task": "ocr"}).json()
    assert client.get("/api/v1/models/", params={"enabled": "false"}).json() == []


def test_list_models_bad_task_422(client):
    resp = client.get("/api/v1/models/", params={"task": "teleport"})
    assert resp.status_code == 422


def test_create_model(client):
    resp = client.post("/api/v1/models/", json=NEW_MODEL, headers={"If-Match": "*"})
    assert resp.status_code == 201
    assert resp.headers["location"] == "/api/v1/models/test-model"
    assert resp.headers["etag"].startswith('"')
    body = resp.json()
    for field in ("model_id", "name", "engine_id", "resource", "enabled",
                  "available", "tasks", "tracking", "classes", "keypoints",
                  "skeleton", "metadata"):
        assert field in body
    assert body["available"] is True
    assert body["tracking"] is True


def test_create_model_requires_if_match(client):
    resp = client.post("/api/v1/models/", json=NEW_MODEL)
    assert resp.status_code == 428


def test_create_model_duplicate_409(client):
    client.post("/api/v1/models/", json=NEW_MODEL, headers={"If-Match": "*"})
    resp = client.post("/api/v1/models/", json=NEW_MODEL, headers={"If-Match": "*"})
    assert resp.status_code == 409


def test_create_model_unknown_engine_404(client):
    resp = client.post(
        "/api/v1/models/",
        json={**NEW_MODEL, "model_id": "m2", "engine_id": "ghost"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 404


def test_create_model_empty_resource_422(client):
    resp = client.post(
        "/api/v1/models/",
        json={**NEW_MODEL, "model_id": "m2", "resource": {}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_create_model_bad_identifier_422(client):
    resp = client.post(
        "/api/v1/models/",
        json={**NEW_MODEL, "model_id": "-bad"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_get_model(client):
    resp = client.get("/api/v1/models/synthetic-vision")
    assert resp.status_code == 200
    assert resp.json()["model_id"] == "synthetic-vision"
    assert resp.headers["etag"].startswith('"')


def test_get_unknown_model_404(client):
    assert client.get("/api/v1/models/nope").status_code == 404


def test_patch_model(client):
    client.post("/api/v1/models/", json=NEW_MODEL, headers={"If-Match": "*"})
    resp = client.patch(
        "/api/v1/models/test-model",
        json={"name": "Renamed", "enabled": False},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["enabled"] is False
    assert body["available"] is False


def test_patch_model_requires_if_match(client):
    resp = client.patch("/api/v1/models/synthetic-vision", json={"name": "x"})
    assert resp.status_code == 428


def test_patch_unknown_model_404(client):
    resp = client.patch("/api/v1/models/nope", json={"name": "x"}, headers={"If-Match": "*"})
    assert resp.status_code == 404


def test_patch_model_unknown_engine_404(client):
    resp = client.patch(
        "/api/v1/models/synthetic-vision",
        json={"engine_id": "ghost"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 404


def test_patch_model_null_rejected(client):
    resp = client.patch(
        "/api/v1/models/synthetic-vision",
        json={"enabled": None},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_delete_model(client):
    client.post("/api/v1/models/", json=NEW_MODEL, headers={"If-Match": "*"})
    resp = client.delete("/api/v1/models/test-model", headers={"If-Match": "*"})
    assert resp.status_code == 204
    assert resp.headers["etag"].startswith('"')
    assert client.get("/api/v1/models/test-model").status_code == 404


def test_delete_model_requires_if_match(client):
    resp = client.delete("/api/v1/models/synthetic-vision")
    assert resp.status_code == 428


def test_delete_unknown_model_404(client):
    resp = client.delete("/api/v1/models/nope", headers={"If-Match": "*"})
    assert resp.status_code == 404


def test_model_validate_ok(client):
    resp = client.post("/api/v1/models/synthetic-vision/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["details"]["engine_id"] == "synthetic"


def test_model_validate_disabled_valid_false(client):
    client.patch(
        "/api/v1/models/synthetic-vision",
        json={"enabled": False},
        headers={"If-Match": "*"},
    )
    resp = client.post("/api/v1/models/synthetic-vision/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert any("disabled" in e for e in body["errors"])


def test_model_validate_unknown_404(client):
    assert client.post("/api/v1/models/nope/validate").status_code == 404

NEW_MODEL = {
    "id": "test-model",
    "engine_id": "synthetic",
    "resource_ref": "/opt/models/test.bin",
    "tasks": ["detection", "ocr"],
}


def test_list_models_includes_seed(client):
    resp = client.get("/api/v1/models/")
    assert resp.status_code == 200
    assert resp.headers["etag"].startswith('"')
    ids = [m["id"] for m in resp.json()]
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
    for field in ("id", "engine_id", "display_name", "tasks", "state",
                  "resource_label", "created_at"):
        assert field in body
    assert body["state"] == "ready"
    assert body["display_name"] == "test-model"
    assert body["tasks"] == ["detection", "ocr"]
    assert body["resource_label"] == "/opt/models/test.bin"


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
        json={**NEW_MODEL, "id": "m2", "engine_id": "ghost"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 404


def test_create_model_empty_resource_422(client):
    resp = client.post(
        "/api/v1/models/",
        json={**NEW_MODEL, "id": "m2", "resource_ref": ""},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_create_model_bad_identifier_422(client):
    resp = client.post(
        "/api/v1/models/",
        json={**NEW_MODEL, "id": "-bad"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_get_model(client):
    resp = client.get("/api/v1/models/synthetic-vision")
    assert resp.status_code == 200
    assert resp.json()["id"] == "synthetic-vision"
    assert resp.headers["etag"].startswith('"')


def test_get_unknown_model_404(client):
    assert client.get("/api/v1/models/nope").status_code == 404


def test_patch_model(client):
    client.post("/api/v1/models/", json=NEW_MODEL, headers={"If-Match": "*"})
    resp = client.patch(
        "/api/v1/models/test-model",
        json={"display_name": "Renamed"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Renamed"


def test_patch_model_requires_if_match(client):
    resp = client.patch("/api/v1/models/synthetic-vision", json={"display_name": "x"})
    assert resp.status_code == 428


def test_patch_unknown_model_404(client):
    resp = client.patch("/api/v1/models/nope", json={"display_name": "x"}, headers={"If-Match": "*"})
    assert resp.status_code == 404


def test_patch_model_extra_field_422(client):
    # engine_id/resource are immutable in v1.5; unknown patch keys are rejected.
    resp = client.patch(
        "/api/v1/models/synthetic-vision",
        json={"engine_id": "ghost"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_patch_model_null_rejected(client):
    resp = client.patch(
        "/api/v1/models/synthetic-vision",
        json={"display_name": None},
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


def test_model_validate_unavailable_valid_false(client):
    client.patch(
        "/api/v1/engines/synthetic",
        json={"enabled": False},
        headers={"If-Match": "*"},
    )
    resp = client.post("/api/v1/models/synthetic-vision/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["errors"]


def test_model_validate_unknown_404(client):
    assert client.post("/api/v1/models/nope/validate").status_code == 404

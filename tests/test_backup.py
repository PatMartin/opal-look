def _export(client):
    resp = client.get("/api/v1/backup/export")
    assert resp.status_code == 200
    assert resp.headers["etag"].startswith('"')
    return resp.json()


def test_export_shape(client):
    body = _export(client)
    assert body["version"] == "1.1.0"
    assert body["exported_at"]
    for key in ("engines", "models", "sources", "profiles", "settings"):
        assert key in body
    assert any(e["engine_id"] == "synthetic" for e in body["engines"])
    assert any(m["model_id"] == "synthetic-vision" for m in body["models"])


def test_validate_current(client):
    resp = client.get("/api/v1/backup/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["errors"] == []


def test_validate_supplied(client):
    payload = _export(client)
    resp = client.post("/api/v1/backup/validate", json=payload)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_validate_invalid_supplied(client):
    payload = _export(client)
    payload["profiles"] = [{"profile_id": 1, "name": "x", "model_id": "ghost",
                            "task": "detection", "settings": {}, "active": True}]
    resp = client.post("/api/v1/backup/validate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert any("unknown model" in e for e in body["errors"])


def test_validate_malformed_422(client):
    assert client.post("/api/v1/backup/validate", json={"x": 1}).status_code == 422


def test_import_roundtrip(client):
    payload = _export(client)
    payload["settings"]["max_upload_bytes"] = 424242
    payload["profiles"] = [
        {"profile_id": 7, "name": "imported", "model_id": "synthetic-vision",
         "task": "detection", "settings": {"confidence": 0.5}, "active": True}
    ]
    resp = client.post("/api/v1/backup/import", json=payload, headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.headers["etag"].startswith('"')
    assert client.get("/api/v1/settings/max_upload_bytes").json()["value"] == 424242
    prof = client.get("/api/v1/profiles/7").json()
    assert prof["active"] is True
    assert prof["settings"]["confidence"] == 0.5


def test_import_requires_if_match(client):
    assert client.post("/api/v1/backup/import", json=_export(client)).status_code == 428


def test_import_rejected_during_session(client, tmp_path=None):
    client.app.state.store._conn.execute(
        "INSERT INTO sessions (session_id, source_id, model_id, engine_id, task, "
        "settings, store_results, state, created_at) "
        "VALUES ('s1', 'x', 'm', 'e', 'detection', '{}', 1, 'running', "
        "'2099-01-01T00:00:00Z')")
    resp = client.post("/api/v1/backup/import", json=_export(client),
                       headers={"If-Match": "*"})
    assert resp.status_code == 409


def test_import_bad_version_422(client):
    payload = _export(client)
    payload["version"] = "9.9.9"
    resp = client.post("/api/v1/backup/import", json=payload, headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_import_atomic_on_error(client):
    payload = _export(client)
    payload["profiles"] = [{"profile_id": 1, "name": "x", "model_id": "ghost",
                            "task": "detection", "settings": {}, "active": True}]
    before = client.get("/api/v1/settings/").json()
    resp = client.post("/api/v1/backup/import", json=payload, headers={"If-Match": "*"})
    assert resp.status_code == 422
    assert client.get("/api/v1/settings/").json() == before
    assert client.get("/api/v1/profiles/").json() == []


def test_backup_create_list_download_delete(client):
    resp = client.post("/api/v1/backup/create")
    assert resp.status_code == 201
    filename = resp.json()["filename"]
    assert resp.headers["location"] == f"/api/v1/backup/download/{filename}"
    listing = client.get("/api/v1/backup/list").json()
    assert any(b["filename"] == filename for b in listing)
    dl = client.get(f"/api/v1/backup/download/{filename}")
    assert dl.status_code == 200 and dl.json()["version"] == "1.1.0"
    assert client.delete(f"/api/v1/backup/{filename}").status_code == 204
    assert client.get(f"/api/v1/backup/download/{filename}").status_code == 404


def test_backup_restore(client):
    filename = client.post("/api/v1/backup/create").json()["filename"]
    client.patch("/api/v1/settings/", json={"max_upload_bytes": 777},
                 headers={"If-Match": "*"})
    resp = client.post(f"/api/v1/backup/restore/{filename}", headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert client.get("/api/v1/settings/max_upload_bytes").json()["value"] == 1073741824


def test_backup_filename_traversal_422(client):
    assert client.get("/api/v1/backup/download/..%2F..%2Fetc").status_code in (404, 422)
    assert client.get("/api/v1/backup/download/bad name").status_code == 422

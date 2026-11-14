"""v1.7.1 MVP backup export/validate/import + managed files."""

from __future__ import annotations


def _mk_profile(client, name="p1", **extra):
    return client.post("/api/v1/profile/", json={"name": name, **extra},
                       headers={"If-Match": "*"})


def test_export_sections(client):
    _mk_profile(client, "exp")
    resp = client.get("/api/v1/backup/export")
    assert resp.status_code == 200
    cfg = resp.json()
    assert set(cfg) >= {"format_version", "exported_at", "settings",
                        "engines", "profiles"}
    assert cfg["format_version"] == "1.0.0"
    assert any(p.get("name") == "exp" for p in cfg["profiles"])
    # retired domains are never exported
    assert not any(k in cfg for k in ("media", "observations", "jobs",
                                      "recordings", "sessions", "sources",
                                      "monitors", "personas"))


def test_validate_gives_concrete_issues(client):
    cfg = {
        "settings": {"frame_cache_seconds": "soon"},
        "profiles": [{"id": 1}],
    }
    resp = client.post("/api/v1/backup/validate", json=cfg)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    msgs = " ".join(i["message"] for i in body["issues"])
    assert "invalid settings" in msgs
    assert "name is required" in msgs
    # validate is non-mutating
    assert client.get("/api/v1/profile/").json() == []


def test_import_replace_atomic(client):
    _mk_profile(client, "old")
    cfg = client.get("/api/v1/backup/export").json()
    cfg["profiles"] = [{"id": 1, "name": "new", "is_active": True}]
    resp = client.post("/api/v1/backup/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["status"] == "imported"
    assert body["validation"]["valid"] is True
    assert body["counts"]["profiles"] == 1
    assert body["revision"]
    names = {p["name"] for p in client.get("/api/v1/profile/").json()}
    assert names == {"new"}


def test_import_invalid_rolls_back(client):
    _mk_profile(client, "keep")
    cfg = client.get("/api/v1/backup/export").json()
    cfg["settings"]["frame_cache_seconds"] = 7.5
    resp = client.post("/api/v1/backup/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    assert {p["name"] for p in client.get("/api/v1/profile/").json()} == {"keep"}


def test_import_stale_etag_412(client):
    cfg = client.get("/api/v1/backup/export").json()
    resp = client.post("/api/v1/backup/import", json={"configuration": cfg},
                       headers={"If-Match": '"stale-etag"'})
    assert resp.status_code == 412


def test_import_rejects_untyped_settings_no_poison(client):
    """A settings section that fails ServiceSettings validation must be
    rejected — never stored as an override that would make
    effective_settings() unvalidatable."""
    cfg = client.get("/api/v1/backup/export").json()
    cfg["settings"]["frame_cache_seconds"] = 30.5
    resp = client.post("/api/v1/backup/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    assert client.get("/api/v1/setting/").status_code == 200
    assert client.get("/api/v1/setting/frame_cache_seconds").json()["value"] == 30


def test_import_roundtrip_preserves_settings(client):
    cfg = client.get("/api/v1/backup/export").json()
    resp = client.post("/api/v1/backup/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert client.get("/api/v1/setting/").json()["frame_cache_seconds"] == 30


def test_import_null_body_without_config_set_422(client):
    """A null body imports the ./config/ file set; none provisioned
    here, so the endpoint reports honestly."""
    resp = client.post("/api/v1/backup/import", content=b"null",
                       headers={"If-Match": "*",
                                "Content-Type": "application/json"})
    assert resp.status_code == 422
    assert "./config/" in resp.json()["error"]["message"]


def test_import_null_body_uses_config_file_set(client, tmp_path, monkeypatch):
    cfg = client.get("/api/v1/backup/export").json()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "bundle.json").write_text(
        __import__("json").dumps(cfg), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    resp = client.post("/api/v1/backup/import", content=b"null",
                       headers={"If-Match": "*",
                                "Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "imported"


# -- service-managed backup files ----------------------------------------------


def test_backup_create_list_download_delete(client):
    resp = client.post("/api/v1/backup/create")
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"].startswith("opal-look-")
    assert body["filename"].endswith(".json")
    assert resp.headers["location"] == \
        f"/api/v1/backup/download/{body['filename']}"

    listed = client.get("/api/v1/backup/list").json()
    assert listed[0]["filename"] == body["filename"]
    assert listed[0]["size_bytes"] > 0
    assert listed[0]["created_at"]

    dl = client.get(resp.headers["location"])
    assert dl.status_code == 200
    assert "octet-stream" in dl.headers["content-type"]
    import json as _j
    assert _j.loads(dl.content)["format_version"] == "1.0.0"

    assert client.delete(f"/api/v1/backup/{body['filename']}").status_code == 204
    assert client.get(
        f"/api/v1/backup/download/{body['filename']}").status_code == 404


def test_backup_filename_guards(client):
    # '..' never reaches the app (URL normalization) — traversal is guarded
    # at the validator level, tested below.
    bad = "x" * 300
    assert client.get(f"/api/v1/backup/download/{bad}").status_code == 422
    assert client.delete(f"/api/v1/backup/{bad}").status_code == 422
    assert client.get("/api/v1/backup/download/nope.json").status_code == 404
    assert client.delete("/api/v1/backup/nope.json").status_code == 404


def test_backup_filename_unit_guards():
    import pytest
    from opal_look.backup import check_backup_filename
    from opal_look.errors import ApiError
    for bad in ("..", ".", "a/b", "a\\b", "", "x" * 300):
        with pytest.raises(ApiError) as exc:
            check_backup_filename(bad)
        assert exc.value.status_code == 422
    check_backup_filename("opal-look-20261110T120000Z.json")


def test_backup_restore_under_if_match(client):
    _mk_profile(client, "restored")
    name = client.post("/api/v1/backup/create").json()["filename"]
    # mutate config after the snapshot
    for p in client.get("/api/v1/profile/").json():
        client.delete(f"/api/v1/profile/{p['id']}", headers={"If-Match": "*"})
    assert client.get("/api/v1/profile/").json() == []

    resp = client.post(f"/api/v1/backup/restore/{name}")
    assert resp.status_code == 428  # If-Match is mandatory
    resp = client.post(f"/api/v1/backup/restore/{name}",
                       headers={"If-Match": '"stale"'})
    assert resp.status_code == 412
    resp = client.post(f"/api/v1/backup/restore/{name}",
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "imported"
    assert body["backup_filename"] == name
    names = {p["name"] for p in client.get("/api/v1/profile/").json()}
    assert "restored" in names


def test_backup_restore_missing_404(client):
    resp = client.post("/api/v1/backup/restore/nope.json",
                       headers={"If-Match": "*"})
    assert resp.status_code == 404

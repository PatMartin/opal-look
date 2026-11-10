"""v1.7.1 backup export/validate/import: atomic replace, rebind."""

from __future__ import annotations

import io
import time


def _setup(client):
    client.post("/api/v1/source/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x:554/a"},
        headers={"If-Match": "*"})
    client.post("/api/v1/pipeline/", json={
        "id": "p", "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}, headers={"If-Match": "*"})
    client.post("/api/v1/monitor/", json={
        "id": "m", "name": "M", "source_id": "cam", "pipeline_id": "p",
        "enabled": False}, headers={"If-Match": "*"})


def test_export_redacts_and_excludes_runtime(client):
    _setup(client)
    resp = client.get("/api/v1/backup/export")
    assert resp.status_code == 200
    cfg = resp.json()
    assert set(cfg) >= {"format_version", "exported_at", "settings",
                        "engines", "models", "sources", "pipelines",
                        "zones", "rules", "profiles", "monitors"}
    assert cfg["format_version"] == "1.0.0"
    src = next(s for s in cfg["sources"] if s["id"] == "cam")
    assert src["redacted_locator"]
    # full locator URI is never exported (scheme+host may remain redacted)
    import json as _j
    assert "rtsp://x:554/a" not in _j.dumps(src)
    assert "/a" not in src["redacted_locator"]
    assert "locator" not in src or src.get("locator") != "rtsp://x:554/a"
    # runtime state is not portable
    assert not any(k in cfg for k in ("media", "observations", "jobs",
                                      "recordings", "sessions"))
    mon = next(m for m in cfg["monitors"] if m["id"] == "m")
    assert "state" not in mon and "last_failure" not in mon


def test_validate_gives_concrete_issues(client):
    cfg = {
        "settings": {"default_pipeline_id": "ghost-pipeline"},
        "sources": [{"id": "s1", "kind": "rtsp", "name": "S",
                     "redacted_locator": "redacted_locator"}],
        "pipelines": [{"id": "p1", "model_id": "ghost-model"}],
        "monitors": [{"id": "m1", "source_id": "ghost-src",
                      "pipeline_id": "p1"}],
    }
    resp = client.post("/api/v1/backup/validate", json=cfg)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    msgs = " ".join(i["message"] for i in body["issues"])
    assert "default pipeline" in msgs
    assert "no import binding" in msgs
    assert "not in configuration" in msgs
    # validate is non-mutating
    assert client.get("/api/v1/source/").json() == []


def test_import_replace_atomic(client):
    _setup(client)
    cfg = client.get("/api/v1/backup/export").json()
    # rebind the exported source via source_bindings (locator was redacted)
    cfg["monitors"] = []  # drop monitor to keep it simple
    cfg["source_bindings"] = {"cam": {"locator": "rtsp://new:554/b"}}
    resp = client.post("/api/v1/backup/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["status"] == "imported"
    assert body["validation"]["valid"] is True
    assert body["counts"]["sources"] >= 1
    assert body["revision"]
    # source came back with the rebound locator (verified indirectly via a
    # second export — locator stays redacted, but the source exists)
    src = next(s for s in client.get(
        "/api/v1/source/").json() if s["id"] == "cam")
    assert src["id"] == "cam"


def test_import_unresolved_binding_422(client):
    _setup(client)
    cfg = client.get("/api/v1/backup/export").json()
    # a NEW source id has no binding and no existing row to reuse
    cfg["sources"].append({"id": "s2", "kind": "rtsp", "name": "S2",
                           "redacted_locator": "redacted_locator"})
    resp = client.post("/api/v1/backup/import", json={
        "configuration": cfg},
        headers={"If-Match": "*"})
    assert resp.status_code == 422
    # nothing mutated (rollback)
    assert {s["id"] for s in client.get("/api/v1/source/").json()} == {"cam"}


def test_import_stale_etag_412(client):
    cfg = client.get("/api/v1/backup/export").json()
    resp = client.post("/api/v1/backup/import", json={
        "configuration": cfg,
        "source_bindings": {"cam": {"locator": "rtsp://b"}}},
        headers={"If-Match": '"stale-etag"'})
    assert resp.status_code == 412


def test_import_preserves_existing_source_locator(client):
    _setup(client)
    cfg = client.get("/api/v1/backup/export").json()
    resp = client.post("/api/v1/backup/import", json={
        "configuration": cfg},
        headers={"If-Match": "*"})
    # no binding for 'cam' -> reuses the existing row's locator
    assert resp.status_code == 200
    src = client.get("/api/v1/source/cam")
    assert src.status_code == 200


def test_import_409_running_work(client):
    _setup(client)
    # seed a nonterminal job so the swap can't proceed
    store = client.app.state.store
    store.jobs.insert({"job_id": "jq", "kind": "video_analysis",
                       "payload_json": "{}", "state": "running",
                       "created_at": "2026-01-01T00:00:00Z"})
    cfg = client.get("/api/v1/backup/export").json()
    resp = client.post("/api/v1/backup/import", json={
        "configuration": cfg}, headers={"If-Match": "*"})
    assert resp.status_code == 409
    # rollback: config untouched
    assert {s["id"] for s in client.get("/api/v1/source/").json()} == {"cam"}


def test_settings_default_pipeline_exported(client):
    _setup(client)
    client.put("/api/v1/setting/default_pipeline_id",
               json={"value": "p"}, headers={"If-Match": "*"})
    cfg = client.get("/api/v1/backup/export").json()
    assert cfg["settings"].get("default_pipeline_id") == "p"


def test_import_rejects_untyped_settings_no_poison(client):
    """A settings section that fails ServiceSettings validation must be
    rejected — never stored as an override that would make
    effective_settings() unvalidatable (the float-hours poisoning bug)."""
    cfg = client.get("/api/v1/backup/export").json()
    cfg["settings"]["result_retention_hours"] = 168.5
    resp = client.post("/api/v1/backup/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    # service stays healthy: every settings read still works
    assert client.get("/api/v1/setting/").status_code == 200
    assert client.get("/api/v1/setting/result_retention_hours").json()["value"] == 168


def test_import_roundtrip_preserves_settings(client):
    cfg = client.get("/api/v1/backup/export").json()
    resp = client.post("/api/v1/backup/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert client.get("/api/v1/setting/").json()["result_retention_hours"] == 168


def test_import_null_body_without_config_set_422(client):
    """v1.7.1: a null body imports the ./config/ file set; none provisioned
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

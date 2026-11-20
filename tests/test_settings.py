import pytest
from fastapi.testclient import TestClient

from opal_look.app import create_app
from opal_look.settings import env_setting_overrides

DEFAULTS = {
    "frame_cache_seconds": 30,
    "sse_replay_seconds": 60,
    "sse_buffer_events": 256,
    "max_concurrent_streams": 4,
    "max_upload_bytes": 1073741824,
    "max_image_pixels": 50000000,
    "max_viewers": 8,
    "source_local_roots": [],
    "source_allowed_hosts": [],
    "source_allow_private": False,
}


def _etag(client):
    return client.get("/api/v1/setting/").headers["etag"]


def test_get_settings_returns_defaults_and_etag(client):
    resp = client.get("/api/v1/setting/")
    assert resp.status_code == 200
    assert resp.json() == DEFAULTS
    etag = resp.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')


def test_settings_map_patch_retired(client):
    """v0.1.0 retires the collection PATCH; writes are per-key only."""
    resp = client.patch("/api/v1/setting/",
                        json={"max_concurrent_streams": 2},
                        headers={"If-Match": "*"})
    assert resp.status_code in (404, 405)


def test_put_wrong_type_rejected(client):
    resp = client.put(
        "/api/v1/setting/max_concurrent_streams",
        json={"value": "4"}, headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_put_null_value_rejected(client):
    resp = client.put(
        "/api/v1/setting/max_concurrent_streams",
        json={"value": None}, headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_put_constraint_violation(client):
    resp = client.put(
        "/api/v1/setting/max_concurrent_streams",
        json={"value": 0}, headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_put_with_stale_etag(client):
    client.put("/api/v1/setting/sse_replay_seconds",
               json={"value": 90}, headers={"If-Match": "*"})
    stale = '"00000000000000000000000000000000"'
    resp = client.put(
        "/api/v1/setting/sse_replay_seconds",
        json={"value": 45}, headers={"If-Match": stale})
    assert resp.status_code == 412
    assert resp.json()["error"]["code"] == "precondition_failed"


def test_get_single_setting(client):
    resp = client.get("/api/v1/setting/max_concurrent_streams")
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "max_concurrent_streams"
    assert body["value"] == 4
    assert body["configured_value"] == 4
    assert body["default"] == 4
    assert body["has_override"] is False
    assert body["is_default"] is True
    assert body["source"] == "default"
    assert body["restart_required"] is False
    assert body["pending_restart"] is False
    assert body["warnings"] == []
    assert resp.headers["etag"].startswith('"')


def test_get_unknown_setting_404(client):
    resp = client.get("/api/v1/setting/no_such_key")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_put_single_setting(client):
    resp = client.put(
        "/api/v1/setting/sse_replay_seconds",
        json={"value": 90},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "sse_replay_seconds"
    assert body["value"] == 90
    assert body["configured_value"] == 90
    assert body["has_override"] is True
    assert body["is_default"] is False
    assert body["source"] == "persisted"
    assert body["updated_at"]
    assert resp.headers["etag"].startswith('"')
    assert client.get("/api/v1/setting/").json()["sse_replay_seconds"] == 90


def test_put_single_setting_invalid_value(client):
    resp = client.put(
        "/api/v1/setting/sse_replay_seconds",
        json={"value": "soon"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_put_unknown_setting_404(client):
    resp = client.put(
        "/api/v1/setting/nope", json={"value": 1}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 404


def test_put_requires_if_match(client):
    resp = client.put("/api/v1/setting/sse_replay_seconds", json={"value": 90})
    assert resp.status_code == 428


def test_delete_setting_restores_default(client):
    client.put(
        "/api/v1/setting/sse_buffer_events",
        json={"value": 64},
        headers={"If-Match": "*"},
    )
    resp = client.delete("/api/v1/setting/sse_buffer_events", headers={"If-Match": "*"})
    assert resp.status_code == 204
    assert resp.headers["etag"].startswith('"')
    assert client.get("/api/v1/setting/").json()["sse_buffer_events"] == 256


def test_delete_unknown_setting_404(client):
    resp = client.delete("/api/v1/setting/nope", headers={"If-Match": "*"})
    assert resp.status_code == 404


def test_delete_requires_if_match(client):
    resp = client.delete("/api/v1/setting/sse_buffer_events")
    assert resp.status_code == 428


def test_revision_shared_across_endpoints(client):
    """The ETag is the single global logical-config revision."""
    settings_etag = client.get("/api/v1/setting/").headers["etag"]
    key_etag = client.get("/api/v1/setting/frame_cache_seconds").headers["etag"]
    assert settings_etag == key_etag


def test_stale_override_keys_ignored(client):
    """Overrides for retired keys (e.g. a pre-migration DB) are ignored, not
    a 500."""
    store = client.app.state.store
    store.settings.set("max_concurrent_sessions", 4)
    store.settings.set("result_retention_hours", 168)
    resp = client.get("/api/v1/setting/")
    assert resp.status_code == 200
    assert resp.json() == DEFAULTS


# -- OPAL_LOOK_<key> environment/.env overlays -------------------------------

_SETTING_ENV = [f"OPAL_LOOK_{k.upper()}" for k in DEFAULTS]


@pytest.fixture()
def clean_setting_env(monkeypatch):
    for var in _SETTING_ENV:
        monkeypatch.delenv(var, raising=False)


def _new_client(tmp_path):
    return TestClient(create_app(data_dir=tmp_path / "data"))


def test_env_overlays_setting(tmp_path, monkeypatch, clean_setting_env):
    """Environment overlay: effective value wins over the persisted layer;
    nothing is written to the store."""
    monkeypatch.setenv("OPAL_LOOK_MAX_CONCURRENT_STREAMS", "9")
    with _new_client(tmp_path) as c:
        assert c.get("/api/v1/setting/").json()["max_concurrent_streams"] == 9
        body = c.get("/api/v1/setting/max_concurrent_streams").json()
        assert body["value"] == 9
        assert body["is_default"] is False
        assert body["source"] == "environment"
        assert body["has_override"] is False
        assert body["configured_value"] == 4
        # The overlay is not persisted: the store stays clean.
        store = c.app.state.store
        assert store.settings.entry("max_concurrent_streams") is None


def test_env_invalid_value_skipped(tmp_path, monkeypatch, clean_setting_env):
    monkeypatch.setenv("OPAL_LOOK_MAX_CONCURRENT_STREAMS", "banana")
    monkeypatch.setenv("OPAL_LOOK_SSE_BUFFER_EVENTS", "0")
    with _new_client(tmp_path) as c:
        body = c.get("/api/v1/setting/").json()
        assert body["max_concurrent_streams"] == 4
        assert body["sse_buffer_events"] == 256


def test_env_masks_persisted_override(
        tmp_path, monkeypatch, clean_setting_env):
    """Environment > persisted: a masked override reports source/environment
    plus a warning, and the persisted value survives as configured_value."""
    with _new_client(tmp_path) as c:
        assert c.put("/api/v1/setting/max_concurrent_streams",
                     json={"value": 2},
                     headers={"If-Match": "*"}).status_code == 200
        monkeypatch.setenv("OPAL_LOOK_MAX_CONCURRENT_STREAMS", "7")
        assert c.get("/api/v1/setting/").json()["max_concurrent_streams"] == 7
        body = c.get("/api/v1/setting/max_concurrent_streams").json()
        assert body["value"] == 7
        assert body["configured_value"] == 2
        assert body["source"] == "environment"
        assert body["has_override"] is True
        assert body["is_default"] is False
        assert any(w["code"] == "masked_by_environment" for w in body["warnings"])
        # Removing the overlay restores the persisted value live.
        monkeypatch.delenv("OPAL_LOOK_MAX_CONCURRENT_STREAMS")
        assert c.get("/api/v1/setting/").json()["max_concurrent_streams"] == 2


def test_dotenv_overlay_source(
        tmp_path, monkeypatch, clean_setting_env):
    """A value loaded from the dotenv file reports source=dotenv."""
    env_file = tmp_path / ".env"
    env_file.write_text("OPAL_LOOK_MAX_VIEWERS=3\n", encoding="utf-8")
    # Simulate prepare(): the file var is recorded and load_dotenv placed
    # the value into the process environment.
    monkeypatch.setenv("OPAL_DOTENV_FILE", str(env_file))
    monkeypatch.setenv("OPAL_LOOK_MAX_VIEWERS", "3")
    with _new_client(tmp_path) as c:
        body = c.get("/api/v1/setting/max_viewers").json()
        assert body["value"] == 3
        assert body["source"] == "dotenv"


def test_env_reserved_vars_ignored(tmp_path, monkeypatch, clean_setting_env):
    monkeypatch.setenv("OPAL_LOOK_PORT", "9999")
    monkeypatch.setenv("OPAL_LOOK_CRED_CAM", "u:p")
    monkeypatch.setenv("OPAL_LOOK_NOT_A_SETTING", "5")
    with _new_client(tmp_path) as c:
        assert c.get("/api/v1/setting/").json() == DEFAULTS


def test_env_never_bumps_revision(tmp_path, monkeypatch,
                                  clean_setting_env):
    """Overlays are read-time only; startup never writes or bumps revision."""
    monkeypatch.setenv("OPAL_LOOK_MAX_CONCURRENT_STREAMS", "9")
    with _new_client(tmp_path) as c:
        rev1 = c.app.state.store.config_revision()
    with _new_client(tmp_path) as c:
        assert c.app.state.store.config_revision() == rev1


def test_env_setting_overrides_parsing():
    out = env_setting_overrides({
        "OPAL_LOOK_MAX_CONCURRENT_STREAMS": "6",
        "OPAL_LOOK_PORT": "8002",
        "PATH": "x",
    })
    assert out == {"max_concurrent_streams": 6}

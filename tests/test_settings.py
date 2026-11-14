import pytest

DEFAULTS = {
    "frame_cache_seconds": 30,
    "sse_replay_seconds": 60,
    "sse_buffer_events": 256,
    "max_concurrent_streams": 4,
    "max_upload_bytes": 1073741824,
    "max_image_pixels": 50000000,
    "max_viewers": 8,
}


def _etag(client):
    return client.get("/api/v1/setting/").headers["etag"]


def test_get_settings_returns_defaults_and_etag(client):
    resp = client.get("/api/v1/setting/")
    assert resp.status_code == 200
    assert resp.json() == DEFAULTS
    etag = resp.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')


def test_patch_requires_if_match(client):
    resp = client.patch("/api/v1/setting/", json={"max_concurrent_streams": 2})
    assert resp.status_code == 428
    assert resp.json()["error"]["code"] == "precondition_required"


def test_patch_with_matching_etag(client):
    etag = _etag(client)
    resp = client.patch(
        "/api/v1/setting/",
        json={"max_concurrent_streams": 2, "sse_replay_seconds": 90},
        headers={"If-Match": etag},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_concurrent_streams"] == 2
    assert body["sse_replay_seconds"] == 90
    assert resp.headers["etag"] != etag


def test_patch_with_star(client):
    resp = client.patch(
        "/api/v1/setting/", json={"frame_cache_seconds": 45}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 200
    assert resp.json()["frame_cache_seconds"] == 45


def test_patch_with_stale_etag(client):
    client.patch("/api/v1/setting/", json={"sse_replay_seconds": 90}, headers={"If-Match": "*"})
    stale = '"00000000000000000000000000000000"'
    resp = client.patch(
        "/api/v1/setting/", json={"sse_replay_seconds": 45}, headers={"If-Match": stale}
    )
    assert resp.status_code == 412
    assert resp.json()["error"]["code"] == "precondition_failed"


@pytest.mark.parametrize(
    "if_match",
    ["unquoted", 'W/"weak"', '"a", "b"', ""],
)
def test_patch_malformed_if_match(client, if_match):
    resp = client.patch(
        "/api/v1/setting/", json={"sse_replay_seconds": 90}, headers={"If-Match": if_match}
    )
    assert resp.status_code == 422


def test_patch_empty_rejected(client):
    resp = client.patch("/api/v1/setting/", json={}, headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_patch_unknown_field_rejected(client):
    resp = client.patch(
        "/api/v1/setting/", json={"bogus_setting": 1}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_wrong_type_rejected(client):
    resp = client.patch(
        "/api/v1/setting/", json={"max_concurrent_streams": "4"}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_bool_for_int_rejected(client):
    resp = client.patch(
        "/api/v1/setting/", json={"max_concurrent_streams": True}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_null_value_rejected(client):
    resp = client.patch(
        "/api/v1/setting/", json={"max_concurrent_streams": None}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_constraint_violation(client):
    resp = client.patch(
        "/api/v1/setting/", json={"max_concurrent_streams": 0}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_is_atomic(client):
    resp = client.patch(
        "/api/v1/setting/",
        json={"max_concurrent_streams": 7, "bogus": 1},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422
    assert client.get("/api/v1/setting/").json()["max_concurrent_streams"] == 4


def test_get_single_setting(client):
    resp = client.get("/api/v1/setting/max_concurrent_streams")
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "max_concurrent_streams"
    assert body["value"] == 4
    assert body["is_default"] is True
    assert body["default"] == 4
    assert body["pending_restart"] is False
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
    assert body["is_default"] is False
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

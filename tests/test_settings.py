import pytest

DEFAULTS = {
    "result_retention_hours": 168,
    "media_retention_hours": 24,
    "snapshot_retention_hours": 168,
    "frame_cache_seconds": 30,
    "sse_replay_seconds": 60,
    "sse_buffer_events": 256,
    "max_concurrent_sessions": 4,
    "max_upload_bytes": 1073741824,
    "max_image_pixels": 50000000,
    "max_analysis_timeout_seconds": 60,
    "max_preview_fps": 5,
    "max_result_query_limit": 1000,
    "events_enabled": False,
    "event_topics_allowlist": [
        "opal.look.session.started",
        "opal.look.session.completed",
        "opal.look.session.failed",
        "opal.look.analysis.completed",
    ],
    "max_analysis_events_per_second": 5,
    "event_queue_capacity": 256,
    "default_pipeline_id": None,
}


def _etag(client):
    return client.get("/api/v1/settings/").headers["etag"]


def test_get_settings_returns_defaults_and_etag(client):
    resp = client.get("/api/v1/settings/")
    assert resp.status_code == 200
    assert resp.json() == DEFAULTS
    etag = resp.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')


def test_patch_requires_if_match(client):
    resp = client.patch("/api/v1/settings/", json={"max_concurrent_sessions": 2})
    assert resp.status_code == 428
    assert resp.json()["error"]["code"] == "precondition_required"


def test_patch_with_matching_etag(client):
    etag = _etag(client)
    resp = client.patch(
        "/api/v1/settings/",
        json={"max_concurrent_sessions": 2, "sse_replay_seconds": 90},
        headers={"If-Match": etag},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_concurrent_sessions"] == 2
    assert body["sse_replay_seconds"] == 90
    assert resp.headers["etag"] != etag


def test_patch_with_star(client):
    resp = client.patch(
        "/api/v1/settings/", json={"frame_cache_seconds": 45}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 200
    assert resp.json()["frame_cache_seconds"] == 45


def test_patch_with_stale_etag(client):
    client.patch("/api/v1/settings/", json={"max_preview_fps": 3}, headers={"If-Match": "*"})
    stale = '"00000000000000000000000000000000"'
    resp = client.patch(
        "/api/v1/settings/", json={"max_preview_fps": 4}, headers={"If-Match": stale}
    )
    assert resp.status_code == 412
    assert resp.json()["error"]["code"] == "precondition_failed"


@pytest.mark.parametrize(
    "if_match",
    ["unquoted", 'W/"weak"', '"a", "b"', ""],
)
def test_patch_malformed_if_match(client, if_match):
    resp = client.patch(
        "/api/v1/settings/", json={"max_preview_fps": 3}, headers={"If-Match": if_match}
    )
    assert resp.status_code == 422


def test_patch_empty_rejected(client):
    resp = client.patch("/api/v1/settings/", json={}, headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_patch_unknown_field_rejected(client):
    resp = client.patch(
        "/api/v1/settings/", json={"bogus_setting": 1}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_wrong_type_rejected(client):
    resp = client.patch(
        "/api/v1/settings/", json={"max_concurrent_sessions": "4"}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_bool_for_int_rejected(client):
    resp = client.patch(
        "/api/v1/settings/", json={"max_concurrent_sessions": True}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_null_value_rejected(client):
    resp = client.patch(
        "/api/v1/settings/", json={"max_concurrent_sessions": None}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_constraint_violation(client):
    resp = client.patch(
        "/api/v1/settings/", json={"max_concurrent_sessions": 0}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_is_atomic(client):
    resp = client.patch(
        "/api/v1/settings/",
        json={"max_concurrent_sessions": 7, "bogus": 1},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422
    assert client.get("/api/v1/settings/").json()["max_concurrent_sessions"] == 4


def test_patch_events_enabled_without_transport(client):
    resp = client.patch(
        "/api/v1/settings/", json={"events_enabled": True}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_patch_duplicate_topics_rejected(client):
    resp = client.patch(
        "/api/v1/settings/",
        json={"event_topics_allowlist": ["opal.look.session.started", "opal.look.session.started"]},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_get_single_setting(client):
    resp = client.get("/api/v1/settings/max_concurrent_sessions")
    assert resp.status_code == 200
    assert resp.json() == {"key": "max_concurrent_sessions", "value": 4}
    assert resp.headers["etag"].startswith('"')


def test_get_unknown_setting_404(client):
    resp = client.get("/api/v1/settings/no_such_key")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_put_single_setting(client):
    resp = client.put(
        "/api/v1/settings/media_retention_hours",
        json={"value": 48},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"key": "media_retention_hours", "value": 48}
    assert resp.headers["etag"].startswith('"')
    assert client.get("/api/v1/settings/").json()["media_retention_hours"] == 48


def test_put_single_setting_invalid_value(client):
    resp = client.put(
        "/api/v1/settings/media_retention_hours",
        json={"value": "soon"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_put_unknown_setting_404(client):
    resp = client.put(
        "/api/v1/settings/nope", json={"value": 1}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 404


def test_put_requires_if_match(client):
    resp = client.put("/api/v1/settings/media_retention_hours", json={"value": 48})
    assert resp.status_code == 428


def test_delete_setting_restores_default(client):
    client.put(
        "/api/v1/settings/sse_buffer_events",
        json={"value": 64},
        headers={"If-Match": "*"},
    )
    resp = client.delete("/api/v1/settings/sse_buffer_events", headers={"If-Match": "*"})
    assert resp.status_code == 204
    assert resp.headers["etag"].startswith('"')
    assert client.get("/api/v1/settings/").json()["sse_buffer_events"] == 256


def test_delete_unknown_setting_404(client):
    resp = client.delete("/api/v1/settings/nope", headers={"If-Match": "*"})
    assert resp.status_code == 404


def test_delete_requires_if_match(client):
    resp = client.delete("/api/v1/settings/sse_buffer_events")
    assert resp.status_code == 428


def test_revision_shared_across_endpoints(client):
    """The ETag is the single global logical-config revision."""
    settings_etag = client.get("/api/v1/settings/").headers["etag"]
    key_etag = client.get("/api/v1/settings/frame_cache_seconds").headers["etag"]
    assert settings_etag == key_etag

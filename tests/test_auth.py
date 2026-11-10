"""BearerAuth boundary: 401s on /api/v1, dev mode, bind guard, redaction."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opal_look.app import create_app
from opal_look.auth import assert_bind_allowed, is_loopback_host

TOKEN = "test-bearer-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def authed(tmp_path):
    """App with bearer auth configured (authenticated deployment)."""
    app = create_app(data_dir=tmp_path / "data", auth_token=TOKEN)
    with TestClient(app) as c:
        yield c


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (9, 9, 9)).save(buf, format="PNG")
    return buf.getvalue()


def test_json_endpoint_requires_auth(authed):
    resp = authed.get("/api/v1/setting/")
    assert resp.status_code == 401
    body = resp.json()["error"]
    assert body["code"] == "unauthorized"
    assert resp.headers["www-authenticate"] == "Bearer"
    # Envelope + correlation headers are present even on 401.
    assert body["request_id"] == resp.headers["x-opal-request-id"]
    assert "x-opal-transaction-id" in resp.headers


def test_wrong_and_malformed_credentials(authed):
    assert authed.get("/api/v1/setting/",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert authed.get("/api/v1/setting/",
                      headers={"Authorization": "Basic dXNlcjpwYXNz"}).status_code == 401
    assert authed.get("/api/v1/setting/",
                      headers={"Authorization": "Bearer"}).status_code == 401
    assert authed.get("/api/v1/setting/",
                      headers={"Authorization": "Bearer "}).status_code == 401
    # A wellformed but wrong token is invalid credentials -> 401, not 403.
    body = authed.get("/api/v1/setting/",
                      headers={"Authorization": "Bearer wrong"}).json()["error"]
    assert body["code"] == "unauthorized"


def test_valid_token_allows_json_mutation(authed):
    resp = authed.patch(
        "/api/v1/setting/", json={"max_upload_bytes": 9},
        headers={**AUTH, "If-Match": "*"},
    )
    assert resp.status_code == 200


def test_binary_endpoint_auth(authed):
    # Upload requires auth first.
    denied = authed.post(
        "/api/v1/media/", files={"file": ("x.png", _png_bytes(), "image/png")}
    )
    assert denied.status_code == 401
    mid = authed.post(
        "/api/v1/media/", files={"file": ("x.png", _png_bytes(), "image/png")},
        headers=AUTH,
    ).json()["id"]
    assert authed.get(f"/api/v1/media/{mid}").status_code == 401
    ok = authed.get(f"/api/v1/media/{mid}", headers=AUTH)
    assert ok.status_code == 200
    assert ok.headers["x-opal-transaction-id"]


def test_streaming_endpoint_auth_gate(authed):
    """Auth is enforced before route resolution on stream paths too."""
    assert authed.get("/api/v1/session/nope/events").status_code == 401
    # With a valid token the same path reaches the handler (404 unknown session).
    assert authed.get("/api/v1/session/nope/events", headers=AUTH).status_code == 404


def test_auth_precedes_resource_existence(authed):
    """Unauthenticated callers cannot probe path existence."""
    assert authed.get("/api/v1/does/not/exist").status_code == 401


def test_service_surface_outside_api_stays_open(authed):
    assert authed.get("/health").status_code == 200
    assert authed.get("/").status_code == 200


def test_token_never_echoed(authed):
    resp = authed.get("/api/v1/setting/",
                      headers={"Authorization": "Bearer secret-attempt"})
    assert resp.status_code == 401
    assert "secret-attempt" not in resp.text
    assert "Bearer secret-attempt" not in str(resp.headers)


def test_exports_and_diagnostics_contain_no_token(authed):
    export = authed.get("/api/v1/backup/export", headers=AUTH)
    assert export.status_code == 200
    assert TOKEN not in export.text
    health = authed.get("/api/v1/health/", headers=AUTH)
    assert health.status_code == 200
    assert TOKEN not in health.text


def test_dev_mode_without_token(client):
    """Unconfigured deployments (loopback dev mode) serve without auth."""
    assert client.get("/api/v1/setting/").status_code == 200


def test_empty_token_is_misconfiguration(tmp_path):
    with pytest.raises(ValueError):
        create_app(data_dir=tmp_path / "data", auth_token="   ")


def test_loopback_detection():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("127.4.5.6")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert is_loopback_host("[::1]")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.10")
    assert not is_loopback_host("::")


def test_non_loopback_requires_token():
    assert_bind_allowed("127.0.0.1", None)          # loopback dev mode ok
    assert_bind_allowed("localhost", None)
    assert_bind_allowed("0.0.0.0", "tok")           # exposed + authed ok
    with pytest.raises(SystemExit):
        assert_bind_allowed("0.0.0.0", None)        # exposed + open = refused
    with pytest.raises(SystemExit):
        assert_bind_allowed("192.168.1.10", None)


def test_env_token_empty_is_error(monkeypatch):
    from opal_look.auth import env_token

    monkeypatch.delenv("OPAL_LOOK_TOKEN", raising=False)
    assert env_token() is None
    monkeypatch.setenv("OPAL_LOOK_TOKEN", "  ")
    with pytest.raises(ValueError):
        env_token()

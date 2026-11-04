import re

TOKEN = re.compile(r"^[\x21-\x7e]{1,128}$")


def test_supplied_ids_are_echoed(client):
    resp = client.get("/health", headers={
        "X-Opal-Session-Id": "sess-1",
        "X-Opal-Transaction-Id": "txn-1",
        "X-Opal-Request-Id": "req-1",
        "X-Opal-Causation-Id": "cause-1",
    })
    assert resp.status_code == 200
    assert resp.headers["x-opal-session-id"] == "sess-1"
    assert resp.headers["x-opal-transaction-id"] == "txn-1"
    assert resp.headers["x-opal-request-id"] == "req-1"
    assert resp.headers["x-opal-causation-id"] == "cause-1"


def test_missing_ids_are_generated(client):
    resp = client.get("/health")
    assert TOKEN.match(resp.headers["x-opal-transaction-id"])
    assert TOKEN.match(resp.headers["x-opal-request-id"])
    # Session/causation IDs are only returned when known.
    assert "x-opal-session-id" not in resp.headers
    assert "x-opal-causation-id" not in resp.headers


def test_invalid_header_value_returns_422(client):
    resp = client.get("/health", headers={"X-Opal-Transaction-Id": "has space"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "invalid_correlation_header"
    assert "X-Opal-Transaction-Id" in body["error"]["details"]["headers"]


def test_overlong_header_value_returns_422(client):
    resp = client.get("/health", headers={"X-Opal-Request-Id": "x" * 129})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_correlation_header"


def test_unhandled_error_keeps_correlation_ids(tmp_path):
    """Unhandled exceptions surface as OpalError 500 with the request's IDs
    and X-Opal-* headers intact (the framework 500 path sits outside the
    middleware and would lose them)."""
    from fastapi.testclient import TestClient

    from opal_look.app import create_app

    app = create_app(data_dir=tmp_path / "data")

    @app.get("/api/v1/_boom")
    def _boom():
        raise ValueError("kaboom")

    with TestClient(app) as c:
        resp = c.get("/api/v1/_boom", headers={
            "X-Opal-Session-Id": "sess-x",
            "X-Opal-Transaction-Id": "txn-x",
        })
    assert resp.status_code == 500
    body = resp.json()["error"]
    assert body["code"] == "operation_failed"
    assert body["transaction_id"] == "txn-x"
    assert body["session_id"] == "sess-x"
    assert body["request_id"] == resp.headers["x-opal-request-id"]
    assert resp.headers["x-opal-transaction-id"] == "txn-x"
    assert resp.headers["x-opal-session-id"] == "sess-x"


def test_binary_response_carries_correlation_headers(client):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (5, 5, 5)).save(buf, format="PNG")
    mid = client.post(
        "/api/v1/media/", files={"file": ("x.png", buf.getvalue(), "image/png")}
    ).json()["id"]
    resp = client.get(
        f"/api/v1/media/{mid}/content",
        headers={"X-Opal-Transaction-Id": "txn-bin"},
    )
    assert resp.status_code == 200
    assert resp.headers["x-opal-transaction-id"] == "txn-bin"
    assert TOKEN.match(resp.headers["x-opal-request-id"])


def test_internal_session_ids_never_leak_into_x_opal_header(client):
    """X-Opal-Session-Id is the caller's logical context only; internal
    worker/session identities stay in the body, never in the header."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (4, 4, 4)).save(buf, format="JPEG")
    mid = client.post(
        "/api/v1/media/", files={"file": ("x.jpg", buf.getvalue(), "image/jpeg")}
    ).json()["id"]
    client.post(
        "/api/v1/sources/",
        json={"id": "ms", "name": "M", "kind": "media", "locator": mid},
        headers={"If-Match": "*"},
    )
    resp = client.post(
        "/api/v1/sessions/",
        json={"source_id": "ms", "model_id": "synthetic-vision",
              "task": "detection"},
        headers={"X-Opal-Session-Id": "caller-logical-ctx"},
    )
    assert resp.status_code == 202
    internal = resp.json()["session_id"]
    assert internal.startswith("session-")
    assert resp.headers["x-opal-session-id"] == "caller-logical-ctx"
    assert resp.headers["x-opal-session-id"] != internal

    # Let the worker finish before the store closes underneath it.
    import time

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        row = client.get(f"/api/v1/sessions/{internal}").json()
        if row["state"] in ("stopped", "completed", "failed"):
            break
        time.sleep(0.05)

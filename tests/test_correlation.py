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

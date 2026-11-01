def _check_envelope(body, request_id, transaction_id):
    error = body["error"]
    assert error["request_id"] == request_id
    assert error["transaction_id"] == transaction_id
    assert error["code"]
    assert error["message"]
    assert "session_id" in error
    assert "causation_id" in error


def test_unknown_route_returns_opal_error(client):
    resp = client.get("/api/v1/nope/")
    assert resp.status_code == 404
    body = resp.json()
    _check_envelope(body, resp.headers["x-opal-request-id"], resp.headers["x-opal-transaction-id"])
    assert body["error"]["code"] == "not_found"


def test_method_not_allowed_returns_opal_error(client):
    resp = client.post("/api/v1/health/live")
    assert resp.status_code == 405
    _check_envelope(
        resp.json(),
        resp.headers["x-opal-request-id"],
        resp.headers["x-opal-transaction-id"],
    )


def test_error_includes_correlation_headers(client):
    resp = client.get("/api/v1/nope/")
    assert "x-opal-transaction-id" in resp.headers
    assert "x-opal-request-id" in resp.headers

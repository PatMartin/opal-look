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


def test_error_details_is_always_an_object(client):
    """ErrorBody.details must be a JSON object; list-shaped diagnostics are
    wrapped as {"errors": [...]} by the envelope."""
    resp = client.put("/api/v1/setting/max_upload_bytes", json={"value": "notanint"},
                      headers={"If-Match": "*"})
    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert isinstance(details, dict)
    assert isinstance(details["errors"], list)
    assert details["errors"], "validation diagnostics expected"


def test_validation_error_details_shape(client):
    resp = client.post("/api/v1/source/", json={"bogus": True},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert isinstance(details, dict) and isinstance(details["errors"], list)


def test_retryable_flag_on_transient_errors(client):
    """503/429/504 errors are marked retryable; definitive errors omit it."""
    client.post(
        "/api/v1/source/",
        json={"id": "vid", "name": "V", "kind": "file",
              "locator": "Z:/no/such/file.mp4"},
        headers={"If-Match": "*"},
    )
    client.post("/api/v1/pipeline/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "s1", "kind": "inference",
             "model_id": "synthetic-vision", "task": "detection"}]},
        headers={"If-Match": "*"})
    resp = client.post("/api/v1/session/", json={
        "source_id": "vid", "pipeline_id": "p",
    })
    assert resp.status_code == 503
    assert resp.json()["error"]["retryable"] is True

    not_found = client.get("/api/v1/nope/")
    assert not_found.status_code == 404
    assert "retryable" not in not_found.json()["error"]


def test_default_code_map():
    from opal_look.errors import default_code

    assert default_code(400) == "invalid_request"
    assert default_code(401) == "unauthorized"
    assert default_code(403) == "forbidden"
    assert default_code(404) == "not_found"
    assert default_code(412) == "precondition_failed"
    assert default_code(416) == "range_not_satisfiable"
    assert default_code(422) == "invalid_request"
    assert default_code(428) == "precondition_required"
    assert default_code(429) == "capacity_exceeded"
    assert default_code(503) == "service_unavailable"
    assert default_code(599) == "operation_failed"

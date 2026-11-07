def test_list_engines_includes_synthetic(client):
    resp = client.get("/api/v1/engines/")
    assert resp.status_code == 200
    assert resp.headers["etag"].startswith('"')
    engines = {e["engine_id"]: e for e in resp.json()}
    assert "synthetic" in engines
    eng = engines["synthetic"]
    assert eng["enabled"] is True
    assert eng["available"] is True
    assert eng["state"] == "ready"
    assert {t["task"] for t in eng["tasks"]} == {
        "detection", "classification", "segmentation", "pose", "ocr"
    }
    assert eng["version"]
    assert eng["metadata"]["adapter"] == "synthetic"
    assert eng["device_types"] == ["cpu"]
    assert "seed" in eng["options_schema"]["properties"]


def test_get_engine(client):
    resp = client.get("/api/v1/engines/synthetic")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("engine_id", "name", "version", "enabled", "available",
                  "state", "tasks", "device_types", "options_schema",
                  "options", "metadata"):
        assert field in body
    assert resp.headers["etag"].startswith('"')


def test_get_unknown_engine_404(client):
    resp = client.get("/api/v1/engines/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_patch_engine_requires_if_match(client):
    resp = client.patch("/api/v1/engines/synthetic", json={"enabled": False})
    assert resp.status_code == 428


def test_patch_engine_disable_and_enable(client):
    resp = client.patch(
        "/api/v1/engines/synthetic", json={"enabled": False}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["state"] == "disabled"

    resp = client.patch(
        "/api/v1/engines/synthetic", json={"enabled": True}, headers={"If-Match": "*"}
    )
    assert resp.json()["enabled"] is True
    assert resp.json()["state"] == "ready"


def test_patch_engine_config_unknown_key_422(client):
    resp = client.patch(
        "/api/v1/engines/synthetic",
        json={"options": {"bogus": 1}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_patch_engine_config_force_unavailable(client):
    resp = client.patch(
        "/api/v1/engines/synthetic",
        json={"options": {"force_unavailable": True}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "unavailable"
    # Readiness drops while the only engine is unavailable.
    assert client.get("/api/v1/health/ready").status_code == 503


def test_patch_engine_stale_etag(client):
    resp = client.patch(
        "/api/v1/engines/synthetic",
        json={"enabled": False},
        headers={"If-Match": '"deadbeef"'},
    )
    assert resp.status_code == 412


def test_patch_engine_null_rejected(client):
    resp = client.patch(
        "/api/v1/engines/synthetic", json={"enabled": None}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_engine_validate_route_removed(client):
    """Upstream v1.5.0 has no per-engine validate operation."""
    resp = client.post("/api/v1/engines/synthetic/validate")
    assert resp.status_code in (404, 405)

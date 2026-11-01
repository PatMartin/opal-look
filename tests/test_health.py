def test_service_info(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "opal-look-svc"
    assert body["version"]
    assert body["api_version"] == "v1"
    assert body["contract_version"] == "1.4.0"


def test_liveness_alias(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_live_probe(client):
    resp = client.get("/api/v1/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ready"] is True


def test_ready_probe_not_ready_without_models(client):
    # No registered models/engines yet -> vision readiness is false (503).
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["status"] == "unavailable"


def test_suite_health_shape(client):
    resp = client.get("/api/v1/health/")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("status", "ready", "engines", "active_sessions", "details",
                  "media_capabilities", "event_publication"):
        assert field in body
    assert body["ready"] is False
    assert body["engines"] == []
    assert body["active_sessions"] == 0
    caps = body["media_capabilities"]
    assert "image/jpeg" in caps["image_content_types"]
    assert "image/png" in caps["image_content_types"]
    assert caps["max_upload_bytes"] >= 1
    assert caps["max_image_pixels"] >= 1
    pub = body["event_publication"]
    assert pub["enabled"] is False
    assert pub["status"] == "disabled"

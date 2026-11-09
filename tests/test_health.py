def test_service_info(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "opal-look-svc"
    assert body["version"]
    assert body["api_version"] == "v1"
    assert body["contract_version"] == "1.6.0"


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


def test_ready_probe_ready_with_seeded_synthetic_model(client):
    # The seeded synthetic engine + model make the service ready.
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["status"] == "ok"


def test_ready_probe_unavailable_when_engine_disabled(client):
    client.patch("/api/v1/engine/synthetic", json={"enabled": False}, headers={"If-Match": "*"})
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    assert resp.json()["ready"] is False


def test_suite_health_shape(client):
    resp = client.get("/api/v1/health/")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("status", "ready", "version", "engines", "details",
                  "components", "checks", "metrics", "uptime_seconds",
                  "checked_at", "broker_running", "database_ready",
                  "pending_restart_fields", "models_available", "event",
                  "active_tasks"):
        assert field in body
    assert body["ready"] is True
    assert body["database_ready"] is True
    assert body["uptime_seconds"] >= 0
    assert body["broker_running"] is False
    assert body["event"] == "not_configured"
    assert body["active_profile_id"] is None
    engine_ids = [e["engine_id"] for e in body["engines"]]
    assert "synthetic" in engine_ids
    assert body["models_available"] >= 1
    caps = body["details"]["media_capabilities"]
    assert "image/jpeg" in caps["image_content_types"]
    assert "image/png" in caps["image_content_types"]
    assert caps["max_upload_bytes"] >= 1
    assert caps["max_image_pixels"] >= 1
    pub = body["details"]["event_publication"]
    assert pub["enabled"] is False
    assert pub["status"] == "disabled"


def test_spa_served(client):
    assert client.get("/app/").status_code == 200
    assert "OPAL Look" in client.get("/app/").text
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/style.css").status_code == 200

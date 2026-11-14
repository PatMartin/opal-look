def test_service_info(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "opal-look-svc"
    assert body["version"]
    assert body["api_version"] == "v1"
    assert body["contract_version"] == "1.7.1"


def test_liveness_alias(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_info_contract_path(client):
    resp = client.get("/api/v1/info/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "opal-look-svc"
    assert body["version"]
    assert body["api_version"] == "v1"
    assert body["contract_version"] == "1.7.1"
    assert body["description"]


def test_info_ping(client):
    resp = client.get("/api/v1/info/ping")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_live_probe(client):
    resp = client.get("/api/v1/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ready"] is True


def test_ready_probe_ready_with_storage(client):
    # Storage alone makes the service ready; engines are optional.
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["status"] == "ok"


def test_ready_probe_ready_when_engine_disabled(client):
    # A disabled engine degrades health but cannot block readiness —
    # video-only streams need no AI engine.
    client.patch("/api/v1/engine/synthetic", json={"enabled": False}, headers={"If-Match": "*"})
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["ready"] is True


def test_suite_health_shape(client):
    resp = client.get("/api/v1/health/")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("status", "ready", "version", "engines", "details",
                  "components", "checks", "uptime_seconds",
                  "checked_at", "database_ready",
                  "pending_restart_fields"):
        assert field in body
    assert body["ready"] is True
    assert body["database_ready"] is True
    assert body["uptime_seconds"] >= 0
    assert body["active_profile_id"] is None
    engine_ids = [e["engine_id"] for e in body["engines"]]
    assert "synthetic" in engine_ids
    assert body["details"]["storage"] == "ok"


def test_spa_served(client):
    assert client.get("/app/").status_code == 200
    assert "OPAL Look" in client.get("/app/").text
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/style.css").status_code == 200

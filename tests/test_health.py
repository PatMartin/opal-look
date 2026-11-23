def test_service_info(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "opal-look-svc"
    assert body["version"]
    assert body["api_version"] == "v1"
    assert body["contract_version"] == "0.5.0"


def test_liveness_alias(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_info_routes_retired(client):
    """v0.1.0: /api/v1/info/ + /api/v1/info/ping are retired; the merged
    health report carries identity, liveness and readiness."""
    assert client.get("/api/v1/info/").status_code == 404
    assert client.get("/api/v1/info/ping").status_code == 404


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
    # A disabled engine degrades health but cannot block readiness --
    # video-only streams need no AI engine.
    client.patch("/api/v1/engine/synthetic", json={"enabled": False}, headers={"If-Match": "*"})
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["ready"] is True


def test_health_report_shape(client):
    """Kernel OpalHealthReport: identity + live/ready + details diagnostics."""
    resp = client.get("/api/v1/health/")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("name", "version", "api_version", "status", "live",
                  "ready", "details", "checked_at", "uptime_seconds"):
        assert field in body
    assert body["name"] == "opal-look-svc"
    assert body["api_version"] == "v1"
    assert body["status"] in ("ok", "degraded", "error")
    assert body["live"] is True
    assert body["ready"] is True
    assert body["uptime_seconds"] >= 0
    assert body["active_profile_id"] is None
    details = body["details"]
    engine_ids = [e["engine_id"] for e in details["engines"]]
    assert "synthetic" in engine_ids
    assert details["database_ready"] is True
    assert details["components"]["database"]["state"] == "ok"


def test_health_report_degraded_when_engine_unavailable(client):
    """An enabled-but-unavailable engine reports degraded inside details."""
    client.app.state.engine_registry._adapters["synthetic"] = _UnavailableAdapter()
    resp = client.get("/api/v1/health/")
    body = resp.json()
    assert body["status"] == "degraded"
    engines = {e["engine_id"]: e for e in body["details"]["engines"]}
    assert engines["synthetic"]["state"] == "unavailable"


class _UnavailableAdapter:
    def probe(self, config, enabled):
        return False, "adapter offline"

    def capabilities(self):
        return {}

    def metadata(self):
        return {}


def test_spa_served(client):
    assert client.get("/app/").status_code == 200
    assert "OPAL Look" in client.get("/app/").text
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/style.css").status_code == 200

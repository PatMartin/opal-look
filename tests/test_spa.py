"""MVP SPA: static assets served at /app/, no retired endpoints used."""

def test_spa_served(client):
    r = client.get("/app/")
    assert r.status_code == 200
    assert b"opal_look" in r.content or b"app.js" in r.content


def test_spa_js_only_v17_paths(client):
    js = client.get("/app/app.js").text
    # retired endpoints never referenced
    for legacy in ("/api/v1/source", "/api/v1/session", "/api/v1/pipeline",
                   "/api/v1/analyze", "/api/v1/monitor", "/api/v1/persona",
                   "/api/v1/zone", "/api/v1/rule", "/api/v1/media",
                   "/api/v1/job", "/api/v1/observation", "/api/v1/capture",
                   "/api/v1/artifact", "/api/v1/recording",
                   "/api/v1/events", "/api/v1/metrics",
                   "/api/v1/capabilities",
                   "sessionObservations"):
        assert legacy not in js, legacy
    # every v1.7.1 MVP path family is referenced (all 47 ops reachable)
    for path in (
        "/api/v1/stream/",            # start, list, show, stop, events, video, snapshot, metrics
        "/api/v1/predict",
        "/api/v1/model/",             # list, show, load, unload
        "/api/v1/engine/",            # list, show, update, capabilities
        "/api/v1/engine/discover",
        "/api/v1/hardware/",          # list, show
        "/api/v1/profile/",           # list, add, show, update, remove, activate
        "/api/v1/setting/",           # map list/patch + key show/set/remove
        "/api/v1/info/", "/api/v1/info/ping",
        "/api/v1/health/", "/api/v1/health/live", "/api/v1/health/ready",
        "/api/v1/backup/export", "/api/v1/backup/list", "/api/v1/backup/create",
        "/api/v1/backup/restore/", "/api/v1/backup/download/",
        "/api/v1/backup/import", "/api/v1/backup/validate",
        "/api/v1/service/log", "/api/v1/service/start", "/api/v1/service/stop",
    ):
        assert path in js, path


def test_spa_no_legacy_sections(client):
    html = client.get("/app/").text
    for legacy in ("sec-sources", "sec-sessions", "sec-pipelines",
                   "sec-analyze", "sec-monitors", "sec-personas",
                   "sec-results", "sec-snapshots", "sec-config"):
        assert legacy not in html

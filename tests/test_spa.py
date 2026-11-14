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
    # v1.7.1 MVP ops are referenced
    for path in ("/api/v1/stream/", "/api/v1/predict", "/api/v1/model/",
                 "/api/v1/engine/", "/api/v1/hardware/", "/api/v1/info/",
                 "/api/v1/backup/export", "/api/v1/backup/list",
                 "/api/v1/backup/create", "/api/v1/backup/restore/",
                 "/api/v1/service/log"):
        assert path in js, path


def test_spa_no_legacy_sections(client):
    html = client.get("/app/").text
    for legacy in ("sec-sources", "sec-sessions", "sec-pipelines",
                   "sec-analyze", "sec-monitors", "sec-personas",
                   "sec-results", "sec-snapshots", "sec-config"):
        assert legacy not in html

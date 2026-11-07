"""v1.5 SPA: static assets served at /app/, no legacy endpoints used."""

def test_spa_served(client):
    r = client.get("/app/")
    assert r.status_code == 200
    assert b"opal_look" in r.content or b"app.js" in r.content


def test_spa_js_only_v15_paths(client):
    js = client.get("/app/app.js").text
    # no legacy v1.4 endpoints referenced
    for legacy in ("/api/v1/results", "/api/v1/snapshots", "/api/v1/backup"):
        assert legacy not in js, legacy
    # v1.5 ops are referenced
    for path in ("/api/v1/sources/", "/api/v1/pipelines/", "/api/v1/analyze/",
                 "/api/v1/monitors/", "/api/v1/configuration/export",
                 "/api/v1/events/status", "/api/v1/metrics/"):
        assert path in js, path


def test_spa_no_legacy_sections(client):
    html = client.get("/app/").text
    for legacy in ("sec-results", "sec-snapshots", "sec-backup"):
        assert legacy not in html

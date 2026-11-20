"""Persona catalog endpoints (kernel persona_collection/item/validate)."""


def _mk(client, persona_id="amy", name="Amy", **extra):
    body = {"persona_id": persona_id, "name": name, **extra}
    return client.post("/api/v1/persona/", json=body,
                       headers={"If-Match": "*"})


def test_create_and_show(client):
    resp = _mk(client, voice_id="en-gb-alan-low")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["persona_id"] == "amy"
    assert body["name"] == "Amy"
    assert body["voice_id"] == "en-gb-alan-low"
    assert body["enabled"] is True
    assert body["origin"] == "local"
    assert body["created_at"] and body["updated_at"]
    assert resp.headers["location"].endswith("/api/v1/persona/amy")
    assert resp.headers["etag"].startswith('"')
    got = client.get("/api/v1/persona/amy")
    assert got.status_code == 200 and got.json()["persona_id"] == "amy"


def test_create_validation(client):
    assert _mk(client).status_code == 201
    assert _mk(client).status_code == 409  # duplicate id
    for bad in ({"name": "x"}, {"persona_id": "p2"},
                {"persona_id": "p2", "name": "x", "bogus": 1},
                {"persona_id": "-bad", "name": "x"},
                {"persona_id": "p2", "name": ""},
                {"persona_id": "p2", "name": "x", "enabled": "yes"}):
        assert client.post("/api/v1/persona/", json=bad,
                           headers={"If-Match": "*"}).status_code == 422, bad


def test_list_and_enabled_filter(client):
    _mk(client, "a", "A")
    _mk(client, "b", "B", enabled=False)
    all_ = client.get("/api/v1/persona/").json()
    assert {p["persona_id"] for p in all_} == {"a", "b"}
    assert client.get("/api/v1/persona/?enabled=true").json()[0][
        "persona_id"] == "a"
    assert client.get("/api/v1/persona/?enabled=false").json()[0][
        "persona_id"] == "b"
    assert client.get("/api/v1/persona/").headers["etag"].startswith('"')


def test_patch(client):
    _mk(client)
    resp = client.patch("/api/v1/persona/amy", json={"name": "Amy Two"},
                        headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Amy Two"
    # null clears nullable fields
    resp = client.patch("/api/v1/persona/amy", json={"voice_id": "v1"},
                        headers={"If-Match": "*"})
    assert resp.json()["voice_id"] == "v1"
    resp = client.patch("/api/v1/persona/amy", json={"voice_id": None},
                        headers={"If-Match": "*"})
    assert resp.json()["voice_id"] is None


def test_patch_rejections(client):
    _mk(client)
    for body in ({}, {"bogus": 1}, {"enabled": "x"}, {"voice_id": ""}):
        assert client.patch("/api/v1/persona/amy", json=body,
                            headers={"If-Match": "*"}).status_code == 422, body


def test_delete(client):
    _mk(client)
    assert client.delete("/api/v1/persona/amy",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get("/api/v1/persona/amy").status_code == 404


def test_unknown_persona_404(client):
    assert client.get("/api/v1/persona/nope").status_code == 404
    assert client.patch("/api/v1/persona/nope", json={"name": "x"},
                        headers={"If-Match": "*"}).status_code == 404
    assert client.delete("/api/v1/persona/nope",
                         headers={"If-Match": "*"}).status_code == 404
    assert client.post("/api/v1/persona/nope/validate").status_code == 404


def test_mutations_require_if_match(client):
    _mk(client)
    assert client.post("/api/v1/persona/",
                       json={"persona_id": "p", "name": "P"}).status_code == 428
    assert client.patch("/api/v1/persona/amy",
                        json={"name": "x"}).status_code == 428
    assert client.delete("/api/v1/persona/amy").status_code == 428
    assert client.patch("/api/v1/persona/amy", json={"name": "x"},
                        headers={"If-Match": '"stale-rev"'}).status_code == 412


def test_validate_enabled_and_disabled(client):
    _mk(client, voice_id="v-1")
    resp = client.post("/api/v1/persona/amy/validate")
    assert resp.status_code == 200
    report = resp.json()
    assert report["valid"] is True
    assert report["errors"] == []
    # voice binding is opaque here -> warning, not error
    assert report["warnings"][0]["code"] == "binding_unresolvable"
    # catalog state unchanged by validate (read-only)
    etag = resp.headers["etag"]
    _mk(client, "off", "Off", enabled=False)
    resp = client.post("/api/v1/persona/off/validate")
    assert resp.json()["valid"] is False
    assert resp.json()["errors"][0]["code"] == "persona_disabled"


def test_personas_survive_in_catalog_on_old_db(tmp_path):
    """A pre-0.1.0 personas table (different column set) is rebuilt into the
    new schema instead of being dropped as retired."""
    import sqlite3
    from opal_look.app import create_app
    from fastapi.testclient import TestClient

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = sqlite3.connect(data_dir / "opal-look.db")
    db.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE personas (
            persona_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        INSERT INTO personas (persona_id, name, active)
        VALUES ('legacy', 'Legacy', 1);
        """)
    db.close()

    with TestClient(create_app(data_dir=data_dir)) as c:
        got = c.get("/api/v1/persona/legacy")
        assert got.status_code == 200
        assert got.json()["name"] == "Legacy"
        assert got.json()["origin"] == "local"
        assert got.json()["enabled"] is True

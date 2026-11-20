"""Kernel OpalProfile endpoints: portable namespaced documents under
/api/v1/profile/ (shared + modules compartments, string ids)."""


def _mk(client, name="p1", **extra):
    return client.post("/api/v1/profile/", json={"name": name, **extra},
                       headers={"If-Match": "*"})


def test_create_and_show(client):
    resp = _mk(client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["name"] == "p1"
    assert body["is_active"] is False
    assert body["shared"] == {}
    assert body["modules"] == {}
    assert body["created_at"] and body["updated_at"]
    assert resp.headers["location"].endswith(f"/api/v1/profile/{body['id']}")
    got = client.get(f"/api/v1/profile/{body['id']}")
    assert got.status_code == 200 and got.json()["id"] == body["id"]
    assert got.headers["etag"].startswith('"')


def test_client_supplied_id_and_conflict(client):
    assert _mk(client, "a", id="home").status_code == 201
    assert client.get("/api/v1/profile/home").status_code == 200
    resp = _mk(client, "b", id="home")
    assert resp.status_code == 409


def test_list(client):
    _mk(client, "a")
    _mk(client, "b")
    resp = client.get("/api/v1/profile/")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


def test_unknown_fields_rejected(client):
    # Closed envelope: v1.7 flat fields are gone, not silently kept.
    assert _mk(client, voice_id="piper").status_code == 422
    assert _mk(client, inference={"confidence": 0.5}).status_code == 422
    assert _mk(client, pipeline_id="ghost").status_code == 422


def test_shared_must_be_empty(client):
    assert _mk(client, shared={}).status_code == 201
    assert _mk(client, shared={"anything": 1}).status_code == 422


def test_own_compartment_must_be_empty(client):
    assert _mk(client, modules={"opal-look": {}}).status_code == 201
    assert _mk(client, modules={"opal-look": {"x": 1}}).status_code == 422


def test_foreign_compartments_preserved(client):
    resp = _mk(client, modules={
        "opal-say": {"voice_id": "en-us-lessac-medium", "speed": 1.1},
        "some-future-mod": {"arbitrary": [1, 2, 3]},
    })
    assert resp.status_code == 201, resp.text
    modules = resp.json()["modules"]
    assert modules["opal-say"] == {"voice_id": "en-us-lessac-medium",
                                   "speed": 1.1}
    assert modules["some-future-mod"] == {"arbitrary": [1, 2, 3]}
    pid = resp.json()["id"]
    got = client.get(f"/api/v1/profile/{pid}").json()
    assert got["modules"] == modules


def test_foreign_compartment_validated(client):
    assert _mk(client, modules={"opal-say": {"bogus": 1}}).status_code == 422
    assert _mk(client, modules={"opal-say": {"speed": 99}}).status_code == 422
    assert _mk(client, modules={"opal-listen": {
        "wakeword_names": ["hey"]}}).status_code == 201
    assert _mk(client, modules={"opal-listen": {
        "wakeword_names": "hey"}}).status_code == 422
    # Unrecognized compartments need only be objects.
    assert _mk(client, modules={"x-mod": "not-an-object"}).status_code == 422


def test_patch_merges_and_bumps_updated_at(client):
    pid = _mk(client).json()["id"]
    resp = client.patch(f"/api/v1/profile/{pid}",
                        json={"description": "d1"},
                        headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "d1"
    assert resp.json()["name"] == "p1"


def test_patch_closed_envelope_and_min_properties(client):
    pid = _mk(client).json()["id"]
    assert client.patch(f"/api/v1/profile/{pid}", json={},
                        headers={"If-Match": "*"}).status_code == 422
    assert client.patch(f"/api/v1/profile/{pid}", json={"bogus": 1},
                        headers={"If-Match": "*"}).status_code == 422
    assert client.patch(f"/api/v1/profile/{pid}", json={"name": None},
                        headers={"If-Match": "*"}).status_code == 422


def test_patch_foreign_compartment_rejected(client):
    pid = _mk(client, modules={"opal-say": {"speed": 1.0}}).json()["id"]
    resp = client.patch(f"/api/v1/profile/{pid}",
                        json={"modules": {"opal-say": {"speed": 2.0}}},
                        headers={"If-Match": "*"})
    assert resp.status_code == 422
    # Stored foreign contents are preserved untouched.
    got = client.get(f"/api/v1/profile/{pid}").json()
    assert got["modules"]["opal-say"] == {"speed": 1.0}


def test_patch_own_compartment_empty_only(client):
    pid = _mk(client).json()["id"]
    assert client.patch(f"/api/v1/profile/{pid}",
                        json={"modules": {"opal-look": {}}},
                        headers={"If-Match": "*"}).status_code == 200
    assert client.patch(f"/api/v1/profile/{pid}",
                        json={"modules": {"opal-look": {"x": 1}}},
                        headers={"If-Match": "*"}).status_code == 422


def test_is_active_false_never_deactivates(client):
    pid = _mk(client, "a", is_active=True).json()["id"]
    resp = client.patch(f"/api/v1/profile/{pid}", json={"is_active": False},
                        headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True  # selection unchanged


def test_single_active_invariant(client):
    a = _mk(client, "a").json()["id"]
    b = _mk(client, "b").json()["id"]
    client.post(f"/api/v1/profile/{a}/activate", headers={"If-Match": "*"})
    client.post(f"/api/v1/profile/{b}/activate", headers={"If-Match": "*"})
    profiles = {p["id"]: p for p in client.get("/api/v1/profile/").json()}
    assert profiles[a]["is_active"] is False
    assert profiles[b]["is_active"] is True
    assert client.get("/api/v1/health/").json()["active_profile_id"] == b


def test_delete(client):
    pid = _mk(client).json()["id"]
    assert client.delete(f"/api/v1/profile/{pid}",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get(f"/api/v1/profile/{pid}").status_code == 404


def test_mutation_requires_if_match(client):
    pid = _mk(client).json()["id"]
    assert client.patch(f"/api/v1/profile/{pid}",
                        json={"name": "x"}).status_code == 428
    assert client.delete(f"/api/v1/profile/{pid}").status_code == 428
    assert client.post("/api/v1/profile/", json={"name": "x"}).status_code == 428
    assert client.post(f"/api/v1/profile/{pid}/activate").status_code == 428


def test_unknown_profile_404(client):
    assert client.get("/api/v1/profile/9999").status_code == 404
    assert client.post("/api/v1/profile/9999/activate",
                       headers={"If-Match": "*"}).status_code == 404


def test_missing_name_422(client):
    assert client.post("/api/v1/profile/", json={"description": "x"},
                       headers={"If-Match": "*"}).status_code == 422


def test_profiles_export_import_roundtrip(client):
    resp = _mk(client, "exp", modules={"some-mod": {"k": 1}})
    pid = resp.json()["id"]
    client.post(f"/api/v1/profile/{pid}/activate", headers={"If-Match": "*"})
    snap = client.post("/api/v1/config/save",
                       json={"destination": "response"}).json()["snapshot"]
    doc = next(p for p in snap["resources"]["profiles"]
               if p.get("name") == "exp")
    assert doc["id"] == pid
    assert doc["modules"] == {"some-mod": {"k": 1}}
    resp = client.post("/api/v1/config/load", json={"snapshot": snap},
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    got = client.get(f"/api/v1/profile/{pid}").json()
    assert got["name"] == "exp"
    assert got["modules"] == {"some-mod": {"k": 1}}
    assert got["is_active"] is True


def test_v17_db_upgrades_to_namespaced(tmp_path):
    """A v1.7-era profiles table upgrades: flat fields are preserved under
    the unrecognized opal-look-legacy compartment, int ids become strings."""
    import json
    import sqlite3
    from opal_look.app import create_app
    from fastapi.testclient import TestClient

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = sqlite3.connect(data_dir / "opal-look.db")
    db.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            model_id TEXT NOT NULL DEFAULT '',
            task TEXT NOT NULL DEFAULT '',
            settings TEXT NOT NULL DEFAULT '{}',
            active INTEGER NOT NULL DEFAULT 0,
            data TEXT NOT NULL DEFAULT '{}'
        );
        INSERT INTO profiles (name, model_id, task, settings, active, data)
        VALUES ('legacy', 'yolo11n', 'detect', '{"threshold": 0.4}', 1,
                '{"retention": {"hours": 24}, "created_at": "2025-01-01T00:00:00Z",
                  "updated_at": "2025-01-02T00:00:00Z"}');
        """)
    db.close()

    with TestClient(create_app(data_dir=data_dir)) as c:
        body = c.get("/api/v1/profile/1").json()
        assert body["id"] == "1"
        assert body["name"] == "legacy"
        assert body["is_active"] is True
        assert body["shared"] == {}
        legacy = body["modules"]["opal-look-legacy"]
        assert legacy["model_id"] == "yolo11n"
        assert legacy["task"] == "detect"
        assert legacy["settings"] == {"threshold": 0.4}
        assert legacy["retention"] == {"hours": 24}
        assert body["created_at"] == "2025-01-01T00:00:00Z"
        assert c.get("/api/v1/health/").json()["active_profile_id"] == "1"

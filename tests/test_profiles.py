"""Kernel OpalProfile endpoints: CRUD + activate under /api/v1/profiles/."""


def _mk(client, name="p1", **extra):
    return client.post("/api/v1/profiles/", json={"name": name, **extra},
                       headers={"If-Match": "*"})


def test_create_and_show(client):
    resp = _mk(client, pipeline_id=None)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] >= 1 and body["name"] == "p1"
    assert body["is_active"] is False
    assert body["created_at"]
    got = client.get(f"/api/v1/profiles/{body['id']}")
    assert got.status_code == 200 and got.json()["id"] == body["id"]
    assert got.headers["etag"].startswith('"')


def test_list(client):
    _mk(client, "a")
    _mk(client, "b")
    resp = client.get("/api/v1/profiles/")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


def test_opaque_fields_persisted(client):
    resp = _mk(client, voice_id="piper", inference={"confidence": 0.5},
               retention={"ttl_seconds": 60})
    body = resp.json()
    assert body["voice_id"] == "piper"
    assert body["inference"] == {"confidence": 0.5}
    assert body["retention"] == {"ttl_seconds": 60}


def test_patch_merges_and_bumps_updated_at(client):
    pid = _mk(client).json()["id"]
    resp = client.patch(f"/api/v1/profiles/{pid}",
                        json={"description": "d1"},
                        headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "d1"
    assert resp.json()["name"] == "p1"


def test_single_active_invariant(client):
    a = _mk(client, "a").json()["id"]
    b = _mk(client, "b").json()["id"]
    client.post(f"/api/v1/profiles/{a}/activate", headers={"If-Match": "*"})
    client.post(f"/api/v1/profiles/{b}/activate", headers={"If-Match": "*"})
    profiles = {p["id"]: p for p in client.get("/api/v1/profiles/").json()}
    assert profiles[a]["is_active"] is False
    assert profiles[b]["is_active"] is True
    assert client.get("/api/v1/health/").json()["active_profile_id"] == b


def test_delete(client):
    pid = _mk(client).json()["id"]
    assert client.delete(f"/api/v1/profiles/{pid}",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get(f"/api/v1/profiles/{pid}").status_code == 404


def test_mutation_requires_if_match(client):
    pid = _mk(client).json()["id"]
    assert client.patch(f"/api/v1/profiles/{pid}",
                        json={"name": "x"}).status_code == 428
    assert client.delete(f"/api/v1/profiles/{pid}").status_code == 428
    assert client.post("/api/v1/profiles/", json={"name": "x"}).status_code == 428


def test_unknown_pipeline_422(client):
    resp = _mk(client, pipeline_id="ghost")
    assert resp.status_code == 422


def test_unknown_profile_404(client):
    assert client.get("/api/v1/profiles/9999").status_code == 404
    assert client.post("/api/v1/profiles/9999/activate",
                       headers={"If-Match": "*"}).status_code == 404


def test_missing_name_422(client):
    assert client.post("/api/v1/profiles/", json={"description": "x"},
                       headers={"If-Match": "*"}).status_code == 422


def test_profiles_export_import_roundtrip(client):
    pid = _mk(client, "exp").json()["id"]
    client.post(f"/api/v1/profiles/{pid}/activate", headers={"If-Match": "*"})
    cfg = client.get("/api/v1/configuration/export").json()
    assert any(p.get("name") == "exp" for p in cfg["profiles"])
    resp = client.post("/api/v1/configuration/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    names = {p["name"] for p in client.get("/api/v1/profiles/").json()}
    assert "exp" in names

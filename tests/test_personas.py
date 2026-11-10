"""Persona resource (v1.6): CRUD + enabled filter + validate + export/import."""

P = {"persona_id": "amy", "name": "Amy", "description": "Front-door observer",
     "voice_id": "en-gb-alan-low", "enabled": True}


def test_crud(client):
    resp = client.post("/api/v1/persona/", json=P, headers={"If-Match": "*"})
    assert resp.status_code == 201, resp.text
    assert resp.headers["Location"] == "/api/v1/persona/amy"
    body = resp.json()
    assert body["persona_id"] == "amy"
    assert body["voice_id"] == "en-gb-alan-low"
    assert body["enabled"] is True
    assert body["created_at"] and body["updated_at"]

    assert client.get("/api/v1/persona/amy").json()["name"] == "Amy"
    assert len(client.get("/api/v1/persona/").json()) == 1

    r = client.patch("/api/v1/persona/amy", json={"enabled": False},
                     headers={"If-Match": "*"})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert r.json()["updated_at"] >= body["updated_at"]

    assert client.delete("/api/v1/persona/amy",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get("/api/v1/persona/amy").status_code == 404


def test_enabled_filter(client):
    client.post("/api/v1/persona/", json=P, headers={"If-Match": "*"})
    client.post("/api/v1/persona/",
                json={**P, "persona_id": "bob", "enabled": False},
                headers={"If-Match": "*"})
    enabled = client.get("/api/v1/persona/", params={"enabled": "true"}).json()
    assert [p["persona_id"] for p in enabled] == ["amy"]
    disabled = client.get("/api/v1/persona/", params={"enabled": "false"}).json()
    assert [p["persona_id"] for p in disabled] == ["bob"]
    assert len(client.get("/api/v1/persona/").json()) == 2


def test_duplicate_persona_id_409(client):
    client.post("/api/v1/persona/", json=P, headers={"If-Match": "*"})
    resp = client.post("/api/v1/persona/", json=P, headers={"If-Match": "*"})
    assert resp.status_code == 409


def test_mutations_require_if_match(client):
    assert client.post("/api/v1/persona/", json=P).status_code == 428
    client.post("/api/v1/persona/", json=P, headers={"If-Match": "*"})
    assert client.patch("/api/v1/persona/amy",
                        json={"name": "A2"}).status_code == 428
    assert client.delete("/api/v1/persona/amy").status_code == 428


def test_unknown_persona_404(client):
    assert client.get("/api/v1/persona/nope").status_code == 404
    assert client.patch("/api/v1/persona/nope", json={"name": "X"},
                        headers={"If-Match": "*"}).status_code == 404
    assert client.delete("/api/v1/persona/nope",
                         headers={"If-Match": "*"}).status_code == 404
    assert client.post("/api/v1/persona/nope/validate").status_code == 404


def test_patch_nullable_fields(client):
    client.post("/api/v1/persona/", json=P, headers={"If-Match": "*"})
    r = client.patch("/api/v1/persona/amy",
                     json={"description": None, "voice_id": None},
                     headers={"If-Match": "*"})
    assert r.status_code == 200
    assert r.json()["description"] is None and r.json()["voice_id"] is None
    # name/enabled cannot be nulled
    assert client.patch("/api/v1/persona/amy", json={"name": None},
                        headers={"If-Match": "*"}).status_code == 422
    assert client.patch("/api/v1/persona/amy", json={},
                        headers={"If-Match": "*"}).status_code == 422


def test_validate(client):
    client.post("/api/v1/persona/", json=P, headers={"If-Match": "*"})
    r = client.post("/api/v1/persona/amy/validate")
    assert r.status_code == 200 and r.json()["valid"] is True

    client.patch("/api/v1/persona/amy", json={"enabled": False},
                 headers={"If-Match": "*"})
    r = client.post("/api/v1/persona/amy/validate")
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert any(i["code"] == "persona_disabled" for i in body["issues"])


def test_export_import_roundtrip(client):
    client.post("/api/v1/persona/", json=P, headers={"If-Match": "*"})
    exp = client.get("/api/v1/backup/export").json()
    personas = exp.get("personas") or exp.get("configuration", {}).get("personas")
    assert personas and personas[0]["persona_id"] == "amy"

    client.delete("/api/v1/persona/amy", headers={"If-Match": "*"})
    assert client.get("/api/v1/persona/").json() == []

    r = client.post("/api/v1/backup/import", json=exp,
                    headers={"If-Match": "*"})
    assert r.status_code == 200, r.text
    got = client.get("/api/v1/persona/").json()
    assert len(got) == 1 and got[0]["persona_id"] == "amy"
    assert got[0]["voice_id"] == "en-gb-alan-low"


def test_validate_import_bad_persona(client):
    exp = client.get("/api/v1/backup/export").json()
    exp["personas"] = [{"persona_id": "bad id!", "name": "X"}]
    r = client.post("/api/v1/backup/validate", json=exp)
    assert r.status_code == 200
    assert r.json()["valid"] is False

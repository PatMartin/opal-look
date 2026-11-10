"""Standalone Rule resource: CRUD + source/zone linkage + kind validation."""

RTSP = {"id": "cam-1", "name": "C", "kind": "rtsp",
        "locator": "rtsp://x:554/a"}
ZONE = {"id": "z1", "source_id": "cam-1", "name": "Gate", "kind": "polygon",
        "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0, "y": 1}]}
R = {"id": "r1", "name": "Entry", "source_id": "cam-1",
     "kind": "enters_zone", "zone_id": "z1"}


def _mk(client):
    client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    client.post("/api/v1/zone/", json=ZONE, headers={"If-Match": "*"})


def test_crud(client):
    _mk(client)
    resp = client.post("/api/v1/rule/", json=R, headers={"If-Match": "*"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == "r1" and body["last_triggered_at"] is None
    assert body["capture_on_match"] is False
    assert client.get("/api/v1/rule/r1").json()["kind"] == "enters_zone"
    assert client.get("/api/v1/rule/", params={"source_id": "cam-1"}
                      ).json()[0]["id"] == "r1"
    r = client.patch("/api/v1/rule/r1",
                     json={"cooldown_ms": 500, "enabled": False},
                     headers={"If-Match": "*"})
    assert r.status_code == 200
    assert r.json()["cooldown_ms"] == 500 and r.json()["enabled"] is False
    assert client.delete("/api/v1/rule/r1",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get("/api/v1/rule/r1").status_code == 404


def test_zone_kind_requires_zone_id(client):
    _mk(client)
    resp = client.post("/api/v1/rule/", json={
        "id": "r2", "name": "X", "source_id": "cam-1", "kind": "enters_zone"},
        headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_zone_must_belong_to_source(client):
    _mk(client)
    client.post("/api/v1/source/", json={**RTSP, "id": "cam-2"},
                headers={"If-Match": "*"})
    resp = client.post("/api/v1/rule/", json={**R, "source_id": "cam-2"},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_unknown_source_and_kind_422(client):
    resp = client.post("/api/v1/rule/", json=R, headers={"If-Match": "*"})
    assert resp.status_code == 422  # no source
    _mk(client)
    resp = client.post("/api/v1/rule/", json={**R, "kind": "bogus"},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_duplicate_id_409_and_if_match(client):
    _mk(client)
    client.post("/api/v1/rule/", json=R, headers={"If-Match": "*"})
    assert client.post("/api/v1/rule/", json=R,
                       headers={"If-Match": "*"}).status_code == 409
    assert client.post("/api/v1/rule/", json=R).status_code == 428
    assert client.patch("/api/v1/rule/r1", json={"name": "x"}).status_code == 428
    assert client.delete("/api/v1/rule/r1").status_code == 428


def test_rules_export_import_roundtrip(client):
    _mk(client)
    client.post("/api/v1/rule/", json=R, headers={"If-Match": "*"})
    cfg = client.get("/api/v1/backup/export").json()
    assert any(r["id"] == "r1" for r in cfg["rules"])
    resp = client.post("/api/v1/backup/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert client.get("/api/v1/rule/r1").status_code == 200

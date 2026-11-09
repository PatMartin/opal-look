"""Standalone Zone resource: CRUD + source linkage + geometry validation."""

import json

RTSP = {"id": "cam-1", "name": "C", "kind": "rtsp",
        "locator": "rtsp://x:554/a"}
Z = {"id": "z1", "source_id": "cam-1", "name": "Gate", "kind": "polygon",
     "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0, "y": 1}]}


def _mk_source(client):
    client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})


def test_crud(client):
    _mk_source(client)
    resp = client.post("/api/v1/zone/", json=Z, headers={"If-Match": "*"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "z1" and resp.json()["enabled"] is True
    assert client.get("/api/v1/zone/z1").json()["kind"] == "polygon"
    assert len(client.get("/api/v1/zone/").json()) == 1
    assert client.get("/api/v1/zone/", params={"source_id": "cam-1"}
                      ).json()[0]["id"] == "z1"
    r = client.patch("/api/v1/zone/z1", json={"enabled": False},
                     headers={"If-Match": "*"})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert client.delete("/api/v1/zone/z1",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get("/api/v1/zone/z1").status_code == 404


def test_unknown_source_422(client):
    resp = client.post("/api/v1/zone/", json=Z, headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_geometry_validation(client):
    _mk_source(client)
    resp = client.post("/api/v1/zone/", json={**Z, "points": Z["points"][:2]},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    resp = client.post("/api/v1/zone/", json={
        **Z, "id": "zl", "kind": "line"}, headers={"If-Match": "*"})
    assert resp.status_code == 422  # line needs exactly 2
    resp = client.post("/api/v1/zone/", json={
        **Z, "id": "zl", "kind": "line", "points": Z["points"][:2]},
        headers={"If-Match": "*"})
    assert resp.status_code == 201


def test_duplicate_id_409(client):
    _mk_source(client)
    client.post("/api/v1/zone/", json=Z, headers={"If-Match": "*"})
    resp = client.post("/api/v1/zone/", json=Z, headers={"If-Match": "*"})
    assert resp.status_code == 409


def test_mutations_require_if_match(client):
    _mk_source(client)
    assert client.post("/api/v1/zone/", json=Z).status_code == 428
    client.post("/api/v1/zone/", json=Z, headers={"If-Match": "*"})
    assert client.patch("/api/v1/zone/z1", json={"name": "x"}).status_code == 428
    assert client.delete("/api/v1/zone/z1").status_code == 428


def test_embedded_zones_harvested(client):
    """Legacy sources.zones column content migrates to the zones table."""
    store = client.app.state.store
    src = store.sources.get("cam-1")
    _mk_source(client)
    with store.write_txn():
        store.sources.insert({
            "source_id": "legacy", "name": "L", "type": "file", "locator": "/x",
            "credential_ref": None, "enabled": 1, "source_options": "{}",
            "zones": [{"id": "lz", "name": "LZ", "kind": "line",
                       "points": [{"x": 0, "y": 0}, {"x": 1, "y": 1}]}],
        })
        # the one-shot migration already ran at startup; clear the marker to
        # re-run it for this test's pre-1.5 embedded data
        store.zones._conn.execute(
            "DELETE FROM meta WHERE key = 'zones_migrated'")
        store._migrate_embedded_zones()
    row = store.zones.get("lz")
    assert row is not None and row["source_id"] == "legacy"
    assert json.loads(row["points"]) == [{"x": 0, "y": 0}, {"x": 1, "y": 1}]


def test_zones_export_import_roundtrip(client):
    _mk_source(client)
    client.post("/api/v1/zone/", json=Z, headers={"If-Match": "*"})
    cfg = client.get("/api/v1/configuration/export").json()
    assert any(z["id"] == "z1" for z in cfg["zones"])
    resp = client.post("/api/v1/configuration/import", json=cfg,
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert client.get("/api/v1/zone/z1").status_code == 200

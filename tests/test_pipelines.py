"""v1.5 pipeline CRUD: simple mode, defaults, ETags, validation, persistence."""

from __future__ import annotations

SIMPLE = {"id": "p1", "name": "Det", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}


def test_create_simple_201(client):
    resp = client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    assert resp.status_code == 201
    assert resp.headers["location"] == "/api/v1/pipelines/p1"
    assert resp.headers["etag"].startswith('"')
    body = resp.json()
    assert body["id"] == "p1"
    assert body["stages"][0]["model_id"] == "synthetic-vision"
    assert body["stages"][0]["task"] == "detection"
    assert body["created_at"]


def test_create_requires_if_match(client):
    assert client.post("/api/v1/pipelines/", json=SIMPLE).status_code == 428


def test_list_and_show(client):
    client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    listed = client.get("/api/v1/pipelines/").json()
    assert listed[0]["id"] == "p1"
    assert client.get("/api/v1/pipelines/").headers["etag"].startswith('"')
    shown = client.get("/api/v1/pipelines/p1").json()
    assert shown["name"] == "Det"
    assert set(shown) <= {"id", "name", "description", "stages", "created_at"}


def test_show_unknown_404(client):
    assert client.get("/api/v1/pipelines/nope").status_code == 404


def test_create_duplicate_409(client):
    client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    assert client.post("/api/v1/pipelines/", json=SIMPLE,
                       headers={"If-Match": "*"}).status_code == 409


def test_create_missing_model_422(client):
    resp = client.post("/api/v1/pipelines/",
                       json={"id": "p2", "name": "G", "stages": [
                           {"id": "s1", "kind": "inference",
                            "model_id": "ghost", "task": "detection"}]},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_create_unsupported_task_422(client):
    resp = client.post("/api/v1/pipelines/",
                       json={"id": "p2", "name": "T", "stages": [
                           {"id": "s1", "kind": "inference",
                            "model_id": "synthetic-vision", "task": "teleport"}]},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    assert "issues" in resp.json()["error"]["details"]


def test_create_unavailable_model_422(client):
    client.patch("/api/v1/engines/synthetic", json={"enabled": False},
                 headers={"If-Match": "*"})
    resp = client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_create_bad_options_422(client):
    resp = client.post("/api/v1/pipelines/",
                       json={**SIMPLE, "options": {"engine_options": {"bogus": 1}}},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_create_retention_over_cap_422(client):
    resp = client.post("/api/v1/pipelines/",
                       json={**SIMPLE, "retention": {"ttl_seconds": 10**12}},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_create_mode_violation_422(client):
    # model_id + stages together -> not exactly one mode
    resp = client.post("/api/v1/pipelines/",
                       json={**SIMPLE, "stages": [{"id": "s1", "kind": "filter"}]},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    # model_id without task -> invalid
    resp = client.post("/api/v1/pipelines/",
                       json={"id": "p2", "name": "X", "model_id": "synthetic-vision"},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_create_advanced_stages_stored(client):
    pipe = {"id": "adv", "name": "A",
            "stages": [{"id": "s1", "kind": "filter",
                        "portable": {"filter": {"type": "grayscale"}}},
                       {"id": "s2", "kind": "inference", "model_id": "synthetic-vision", "task": "detection",
                        "inputs": ["s1"]}]}
    resp = client.post("/api/v1/pipelines/", json=pipe, headers={"If-Match": "*"})
    assert resp.status_code == 201
    stored = resp.json()["stages"]

    def _norm(st):
        st = {k: v for k, v in st.items() if k != "enabled"}
        f = (st.get("portable") or {}).get("filter")
        if f is not None and f.get("parameters") == {}:
            f = dict(f)
            f.pop("parameters")
            st = dict(st)
            st["portable"] = {**st["portable"], "filter": f}
        return st

    for got, want in zip(stored, pipe["stages"]):
        assert _norm(got) == want
        assert got["enabled"] is True


def test_create_advanced_unknown_model_422(client):
    pipe = {"id": "adv", "name": "A",
            "stages": [{"id": "s1", "kind": "inference", "model_id": "ghost", "task": "detection"}]}
    assert client.post("/api/v1/pipelines/", json=pipe,
                       headers={"If-Match": "*"}).status_code == 422


def test_patch_bumps_revision_and_fields(client):
    client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    resp = client.patch("/api/v1/pipelines/p1", json={"name": "New"},
                        headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"
    assert resp.headers["etag"].startswith('"')


def test_patch_stages_replaced(client):
    client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    resp = client.patch("/api/v1/pipelines/p1",
                        json={"stages": [{"id": "s1", "kind": "filter",
                                          "portable": {"filter": {"type": "grayscale"}}},
                                         {"id": "s2", "kind": "inference",
                                          "model_id": "synthetic-vision",
                                          "task": "detection",
                                          "inputs": ["s1"]}]},
                        headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert [s["kind"] for s in resp.json()["stages"]] == ["filter", "inference"]


def test_patch_resolved_invalid_422(client):
    client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    # clearing task but keeping model_id -> half-simple, invalid
    resp = client.patch("/api/v1/pipelines/p1", json={"task": None},
                        headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_patch_stale_etag_412(client):
    client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    resp = client.patch("/api/v1/pipelines/p1", json={"name": "X"},
                        headers={"If-Match": '"deadbeef"'})
    assert resp.status_code == 412


def test_delete_204_and_unknown(client):
    client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    assert client.delete("/api/v1/pipelines/p1",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get("/api/v1/pipelines/p1").status_code == 404


def test_validate_endpoint(client):
    body = client.post("/api/v1/pipelines/validate",
                       json={"id": "v", "name": "V", "stages": [
                           {"id": "s1", "kind": "inference",
                            "model_id": "synthetic-vision", "task": "nope"}]}).json()
    assert body["valid"] is False
    assert body["issues"][0]["severity"] == "error"
    body = client.post("/api/v1/pipelines/validate", json=SIMPLE).json()
    assert body["valid"] is True


def test_default_pipeline_id_setting(client):
    client.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    resp = client.put("/api/v1/settings/default_pipeline_id",
                      json={"value": "p1"}, headers={"If-Match": "*"})
    assert resp.status_code in (200, 204)
    assert "default_pipeline_id" in str(client.get("/api/v1/settings/").json())


def test_persistence_across_restart(tmp_path):
    """Pipelines survive a Store restart in the same data dir."""
    from fastapi.testclient import TestClient
    from opal_look.app import create_app

    c1 = TestClient(create_app(data_dir=str(tmp_path)))
    c1.post("/api/v1/pipelines/", json=SIMPLE, headers={"If-Match": "*"})
    c2 = TestClient(create_app(data_dir=str(tmp_path)))
    body = c2.get("/api/v1/pipelines/p1").json()
    assert body["id"] == "p1" and body["stages"][0]["model_id"] == "synthetic-vision"

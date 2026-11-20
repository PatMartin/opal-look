"""Config snapshot endpoints (kernel config_save/load/validate)."""


def _save_response(client):
    return client.post("/api/v1/config/save",
                       json={"destination": "response"})


def _snapshot(client):
    resp = _save_response(client)
    assert resp.status_code == 200
    return resp.json()["snapshot"]


def test_save_response_shape(client):
    resp = _save_response(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["managed"] is False
    snap = body["snapshot"]
    assert snap["format_version"] == "1.0.0"
    assert snap["module"] == "opal-look"
    assert snap["created_at"]
    assert set(snap["resources"]) == {"profiles", "personas", "engines",
                                      "models"}
    assert resp.headers["etag"].startswith('"')


def test_save_managed_does_not_bump_revision(client):
    etag = client.get("/api/v1/setting/").headers["etag"]
    resp = client.post("/api/v1/config/save", json={})
    assert resp.status_code == 200
    assert resp.json()["managed"] is True
    assert client.get("/api/v1/setting/").headers["etag"] == etag


def test_save_rejects_bad_request(client):
    assert client.post("/api/v1/config/save",
                       json={"destination": "nowhere"}).status_code == 422
    assert client.post("/api/v1/config/save",
                       json={"bogus": 1}).status_code == 422


def test_load_managed_roundtrip(client):
    client.put("/api/v1/setting/max_viewers", json={"value": 5},
               headers={"If-Match": "*"})
    client.post("/api/v1/persona/", json={"persona_id": "amy", "name": "Amy"},
                headers={"If-Match": "*"})
    pid = client.post("/api/v1/profile/", json={"name": "trip"},
                      headers={"If-Match": "*"}).json()["id"]
    client.post("/api/v1/config/save", json={})

    # Dirty the live config, then load the managed snapshot.
    client.put("/api/v1/setting/max_viewers", json={"value": 1},
               headers={"If-Match": "*"})
    client.delete("/api/v1/persona/amy", headers={"If-Match": "*"})
    resp = client.post("/api/v1/config/load", json={},
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is True
    assert body["pending_restart_fields"] == []
    assert client.get("/api/v1/persona/amy").status_code == 200
    assert client.get(f"/api/v1/profile/{pid}").status_code == 200
    # Env mask (.env OPAL_LOOK_MAX_VIEWERS=2) means effective is 2 but the
    # persisted override is restored to 5.
    got = client.get("/api/v1/setting/max_viewers").json()
    assert got["configured_value"] == 5


def test_load_missing_managed_404(client):
    resp = client.post("/api/v1/config/load", json={},
                       headers={"If-Match": "*"})
    assert resp.status_code == 404


def test_load_rejects_null_and_wrong_envelope(client):
    assert client.post("/api/v1/config/load", json={"snapshot": None},
                       headers={"If-Match": "*"}).status_code == 422
    snap = _snapshot(client)
    for bad in ({**snap, "format_version": "9.9.9"},
                {**snap, "module": "opal-say"},
                {**snap, "resources": {**snap["resources"], "bogus": []}},
                {**snap, "settings": {"no_such_key": 1}},
                {**snap, "settings": {"max_viewers": 0}}):
        resp = client.post("/api/v1/config/load", json={"snapshot": bad},
                           headers={"If-Match": "*"})
        assert resp.status_code == 422, bad


def test_load_is_atomic_and_requires_if_match(client):
    snap = _snapshot(client)
    assert client.post("/api/v1/config/load",
                       json={"snapshot": snap}).status_code == 428
    assert client.post("/api/v1/config/load", json={"snapshot": snap},
                       headers={"If-Match": '"stale"'}).status_code == 412
    # Invalid section leaves config untouched.
    bad = {**snap, "resources": {**snap["resources"],
                                 "personas": [{"name": "No Id"}]}}
    assert client.post("/api/v1/config/load", json={"snapshot": bad},
                       headers={"If-Match": "*"}).status_code == 422
    assert client.get("/api/v1/persona/").status_code == 200


def test_load_replaces_not_merges(client):
    client.post("/api/v1/persona/", json={"persona_id": "gone", "name": "G"},
                headers={"If-Match": "*"})
    snap = _snapshot(client)  # snapshot WITHOUT the extra persona later?
    client.post("/api/v1/persona/", json={"persona_id": "extra", "name": "E"},
                headers={"If-Match": "*"})
    resp = client.post("/api/v1/config/load", json={"snapshot": snap},
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    ids = {p["persona_id"] for p in client.get("/api/v1/persona/").json()}
    assert ids == {"gone"}


def test_load_executes_no_actions(client):
    """models section round-trips verbatim as desired state."""
    snap = _snapshot(client)
    snap["resources"]["models"] = [{"model_id": "m1", "loaded": True}]
    resp = client.post("/api/v1/config/load", json={"snapshot": snap},
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    again = _snapshot(client)
    assert again["resources"]["models"] == [{"model_id": "m1",
                                             "loaded": True}]


def test_validate_live_config(client):
    resp = client.post("/api/v1/config/validate", json={})
    assert resp.status_code == 200
    assert resp.json() == {"valid": True, "errors": [], "warnings": []}


def test_validate_candidate_reports_issues(client):
    resp = client.post("/api/v1/config/validate",
                       json={"snapshot": {"bogus": 1}})
    body = resp.json()
    assert body["valid"] is False
    codes = {i["code"] for i in body["errors"]}
    assert {"invalid_envelope", "unsupported_version",
            "wrong_module"} <= codes
    # Non-mutating: revision unchanged.
    etag = client.get("/api/v1/setting/").headers["etag"]
    client.post("/api/v1/config/validate",
                json={"snapshot": _snapshot(client)})
    assert client.get("/api/v1/setting/").headers["etag"] == etag


def test_validate_null_snapshot_422(client):
    assert client.post("/api/v1/config/validate",
                       json={"snapshot": None}).status_code == 422


def test_load_warns_on_unknown_engine(client):
    snap = _snapshot(client)
    snap["resources"]["engines"].append(
        {"engine_id": "ghost-engine", "enabled": True})
    resp = client.post("/api/v1/config/load", json={"snapshot": snap},
                       headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["warnings"][0]["code"] == "unknown_engine"


def test_engine_state_roundtrip(client):
    client.patch("/api/v1/engine/synthetic", json={"enabled": False},
                 headers={"If-Match": "*"})
    snap = _snapshot(client)
    client.patch("/api/v1/engine/synthetic", json={"enabled": True},
                 headers={"If-Match": "*"})
    client.post("/api/v1/config/load", json={"snapshot": snap},
                headers={"If-Match": "*"})
    assert client.get("/api/v1/engine/synthetic").json()["enabled"] is False


def test_backup_routes_retired(client):
    for method, path in (
            ("get", "/api/v1/backup/export"),
            ("post", "/api/v1/backup/import"),
            ("post", "/api/v1/backup/validate"),
            ("post", "/api/v1/backup/create"),
            ("get", "/api/v1/backup/list")):
        assert getattr(client, method)(path).status_code in (404, 405), path

def test_list_models(client):
    client.post("/api/v1/model/synthetic-det/unload")  # shared adapter state
    resp = client.get("/api/v1/model/")
    assert resp.status_code == 200
    models = resp.json()
    assert isinstance(models, list)
    det = [m for m in models if m["model_id"] == "synthetic-det"]
    assert det and det[0]["engine_id"] == "synthetic"
    assert det[0]["tasks"] == ["detection"]
    assert det[0]["loaded"] is False and det[0]["available"] is True


def test_list_models_engine_filter(client):
    resp = client.get("/api/v1/model/", params={"engine_id": "synthetic"})
    assert resp.status_code == 200 and len(resp.json()) == 1
    resp = client.get("/api/v1/model/", params={"engine_id": "ghost"})
    assert resp.status_code == 200 and resp.json() == []


def test_show_model(client):
    resp = client.get("/api/v1/model/synthetic-det")
    assert resp.status_code == 200
    assert resp.json()["model_id"] == "synthetic-det"


def test_show_model_unknown_404(client):
    assert client.get("/api/v1/model/ghost").status_code == 404


def test_load_unload_cycle(client):
    client.post("/api/v1/model/synthetic-det/unload")  # shared adapter state
    resp = client.post("/api/v1/model/synthetic-det/load")
    assert resp.status_code == 200
    assert resp.json()["loaded"] is True
    # load is idempotent
    assert client.post("/api/v1/model/synthetic-det/load").json()["loaded"]
    resp = client.post("/api/v1/model/synthetic-det/unload")
    assert resp.status_code == 200
    assert resp.json()["loaded"] is False


def test_load_unknown_model_404(client):
    assert client.post("/api/v1/model/ghost/load").status_code == 404


def test_load_engine_unavailable_503(client):
    client.patch("/api/v1/engine/synthetic",
                 json={"options": {"force_unavailable": True}},
                 headers={"If-Match": "*"})
    resp = client.post("/api/v1/model/synthetic-det/load")
    assert resp.status_code == 503

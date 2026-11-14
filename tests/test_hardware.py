def test_list_hardware(client):
    resp = client.get("/api/v1/hardware/")
    assert resp.status_code == 200
    devices = resp.json()
    assert isinstance(devices, list)
    cpu = [d for d in devices if d["device_id"] == "cpu"]
    assert cpu and cpu[0]["type"] == "cpu" and cpu[0]["available"] is True
    assert cpu[0]["engine_id"] == "synthetic"


def test_list_hardware_filter_engine(client):
    resp = client.get("/api/v1/hardware/", params={"engine_id": "synthetic"})
    assert resp.status_code == 200
    assert all(d["engine_id"] == "synthetic" for d in resp.json())
    resp = client.get("/api/v1/hardware/", params={"engine_id": "ghost"})
    assert resp.status_code == 200 and resp.json() == []


def test_show_hardware(client):
    resp = client.get("/api/v1/hardware/cpu")
    assert resp.status_code == 200
    assert resp.json()["device_id"] == "cpu"


def test_show_hardware_engine_scoped(client):
    resp = client.get("/api/v1/hardware/cpu", params={"engine_id": "ghost"})
    assert resp.status_code == 404


def test_show_hardware_unknown_404(client):
    assert client.get("/api/v1/hardware/gpu-9").status_code == 404

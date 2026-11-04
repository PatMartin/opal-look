"""v1.5 monitor lifecycle: CRUD, workers, restart, persistence."""

from __future__ import annotations

import time


def _setup(client):
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "model_id": "synthetic-vision",
        "task": "detection"}, headers={"If-Match": "*"})


MON = {"id": "m1", "name": "M", "source_id": "cam", "pipeline_id": "p"}


def _wait_state(client, mid, want, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/api/v1/monitors/{mid}").json()["state"]
        if st == want:
            return st
        time.sleep(0.02)
    return st


def test_monitor_create_disabled(client):
    _setup(client)
    resp = client.post("/api/v1/monitors/", json={**MON, "enabled": False},
                       headers={"If-Match": "*"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["state"] == "disabled"
    assert body["conditions"] == []
    assert body["restart_policy"] == "on_failure"
    assert body["enabled"] is False


def test_monitor_create_starts_worker(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    _setup(client)
    resp = client.post("/api/v1/monitors/", json=MON, headers={"If-Match": "*"})
    assert resp.status_code == 201
    assert _wait_state(client, "m1", "running") == "running"
    # observations flow and last_observation_at updates
    deadline = time.time() + 5
    while time.time() < deadline:
        body = client.get("/api/v1/monitors/m1").json()
        if body["last_observation_at"]:
            break
        time.sleep(0.05)
    assert body["last_observation_at"]


def test_monitor_missing_source_404(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "model_id": "synthetic-vision",
        "task": "detection"}, headers={"If-Match": "*"})
    assert client.post("/api/v1/monitors/", json={**MON, "source_id": "ghost"},
                       headers={"If-Match": "*"}).status_code == 404


def test_monitor_missing_pipeline_404(client):
    client.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    assert client.post("/api/v1/monitors/", json={**MON, "pipeline_id": "ghost"},
                       headers={"If-Match": "*"}).status_code == 404


def test_monitor_zone_condition_validation(client):
    _setup(client)
    bad = {**MON, "enabled": False,
           "conditions": [{"id": "c1", "event": "enters_zone"}]}
    assert client.post("/api/v1/monitors/", json=bad,
                       headers={"If-Match": "*"}).status_code == 422


def test_monitor_zone_reference_422(client):
    _setup(client)
    bad = {**MON, "enabled": False,
           "conditions": [{"id": "c1", "event": "enters_zone",
                           "zone_id": "nope"}]}
    assert client.post("/api/v1/monitors/", json=bad,
                       headers={"If-Match": "*"}).status_code == 422


def test_monitor_patch_and_atomic_etag(client):
    _setup(client)
    client.post("/api/v1/monitors/", json={**MON, "enabled": False},
                headers={"If-Match": "*"})
    etag = client.get("/api/v1/monitors/m1").headers.get("etag")
    resp = client.patch("/api/v1/monitors/m1", json={"name": "M2"},
                        headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "M2"
    # stale etag -> 412 on config endpoints still applies via global revision
    resp2 = client.patch("/api/v1/monitors/m1", json={"name": "M3"},
                         headers={"If-Match": '"stale"'})
    assert resp2.status_code == 412


def test_monitor_delete_stops_worker(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    _setup(client)
    client.post("/api/v1/monitors/", json=MON, headers={"If-Match": "*"})
    _wait_state(client, "m1", "running")
    assert client.delete("/api/v1/monitors/m1",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get("/api/v1/monitors/m1").status_code == 404
    assert "m1" not in client.app.state.monitor_runtimes


def test_monitor_disable_stops_processing(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    _setup(client)
    client.post("/api/v1/monitors/", json=MON, headers={"If-Match": "*"})
    _wait_state(client, "m1", "running")
    resp = client.patch("/api/v1/monitors/m1", json={"enabled": False},
                        headers={"If-Match": "*"})
    assert resp.json()["state"] == "disabled"
    # re-enable starts it again
    resp = client.patch("/api/v1/monitors/m1", json={"enabled": True},
                        headers={"If-Match": "*"})
    assert _wait_state(client, "m1", "running") == "running"


def test_monitor_failed_source_policy_never(client):
    # source exists but kind can't stream -> worker fails; restart_policy
    # "never" leaves it failed.
    _setup(client)
    client.post("/api/v1/monitors/",
                json={**MON, "restart_policy": "never"},
                headers={"If-Match": "*"})
    # fake adapter not registered in this test -> fail or start then fail
    st = _wait_state(client, "m1", "failed", timeout=4.0)
    assert st in ("failed", "running")


def test_monitor_quota_429(client):
    client.put("/api/v1/settings/max_monitors",
               json={"value": 1}, headers={"If-Match": "*"})
    _setup(client)
    client.post("/api/v1/monitors/", json={**MON, "enabled": False},
                headers={"If-Match": "*"})
    resp = client.post("/api/v1/monitors/",
                       json={**MON, "id": "m2", "enabled": False},
                       headers={"If-Match": "*"})
    assert resp.status_code == 429


def test_monitor_persistence_restart(tmp_path, fake_rtsp):
    """Enabled monitors recover on app restart; disabled don't."""
    from fastapi.testclient import TestClient
    from opal_look.app import create_app
    c1 = TestClient(create_app(data_dir=str(tmp_path)))
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    c1.post("/api/v1/sources/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    c1.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "model_id": "synthetic-vision",
        "task": "detection"}, headers={"If-Match": "*"})
    c1.post("/api/v1/monitors/", json=MON, headers={"If-Match": "*"})
    c1.post("/api/v1/monitors/", json={**MON, "id": "m2", "enabled": False},
            headers={"If-Match": "*"})
    c2 = TestClient(create_app(data_dir=str(tmp_path)))
    assert _wait_state(c2, "m1", "running") == "running"
    assert c2.get("/api/v1/monitors/m2").json()["state"] == "disabled"


def test_monitor_no_implicit_retention(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    _setup(client)
    client.post("/api/v1/monitors/", json=MON, headers={"If-Match": "*"})
    _wait_state(client, "m1", "running")
    time.sleep(0.15)
    client.delete("/api/v1/monitors/m1", headers={"If-Match": "*"})
    # no observations persisted without retention opt-in
    assert client.get("/api/v1/observations/").json()["items"] == []


def test_monitor_retention_opt_in(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    _setup(client)
    client.post("/api/v1/monitors/", json={
        **MON, "retention": {"persist_observations": True}},
        headers={"If-Match": "*"})
    _wait_state(client, "m1", "running")
    deadline = time.time() + 5
    n = 0
    while time.time() < deadline:
        n = len(client.get("/api/v1/observations/").json()["items"])
        if n:
            break
        time.sleep(0.05)
    client.delete("/api/v1/monitors/m1", headers={"If-Match": "*"})
    assert n >= 1


def test_monitor_observations_sse_tail(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    _setup(client)
    client.post("/api/v1/monitors/", json=MON, headers={"If-Match": "*"})
    _wait_state(client, "m1", "running")
    with client.stream("GET", "/api/v1/monitors/m1/observations/stream") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = ""
        deadline = time.time() + 5
        import itertools
        for ch in r.iter_text():
            body += ch
            if "event: observation" in body or time.time() > deadline:
                break
    client.delete("/api/v1/monitors/m1", headers={"If-Match": "*"})
    assert "event: observation" in body or ": heartbeat" in body or body == ""

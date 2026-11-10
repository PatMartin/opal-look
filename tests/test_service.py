"""v1.7.1 /service/* — pidfile-managed lifecycle + log tail."""

from __future__ import annotations

import os

import pytest

from opal_look import service_control


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    """Isolate the pidfile/log directory and capture termination calls."""
    monkeypatch.setattr(service_control, "LOG_DIR", tmp_path / "logs")
    calls = {"terminate": [], "kill": [], "spawn": []}
    monkeypatch.setattr(service_control, "terminate_later",
                        lambda delay=1.0: calls["terminate"].append(delay))
    monkeypatch.setattr(service_control, "kill_pid",
                        lambda pid: calls["kill"].append(pid))
    monkeypatch.setattr(service_control, "spawn_server",
                        lambda append=False, wait_pid=None, env_extra=None:
                        calls["spawn"].append((append, wait_pid)) or 4242)
    return calls


def test_log_tail(client, svc):
    logdir = service_control.log_dir()
    logdir.mkdir(parents=True)
    service_control.log_path().write_text(
        "\n".join(f"line{i}" for i in range(15)))
    resp = client.get("/api/v1/service/log")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lines"] == [f"line{i}" for i in range(5, 15)]
    assert body["log_file"].endswith("opal_look.log")
    resp = client.get("/api/v1/service/log", params={"lines": 3})
    assert resp.json()["lines"] == ["line12", "line13", "line14"]


def test_log_404_when_absent(client, svc):
    assert client.get("/api/v1/service/log").status_code == 404


def test_log_lines_bounds(client, svc):
    assert client.get("/api/v1/service/log",
                      params={"lines": 0}).status_code == 422
    assert client.get("/api/v1/service/log",
                      params={"lines": 1001}).status_code == 422


def test_stop_nothing_running(client, svc):
    resp = client.post("/api/v1/service/stop")
    assert resp.status_code == 200
    assert resp.json()["state"] == "stopped"
    assert resp.json()["pid"] is None
    assert svc["kill"] == [] and svc["terminate"] == []


def test_stop_self_delayed_terminate(client, svc):
    service_control.write_pid(os.getpid())
    resp = client.post("/api/v1/service/stop")
    assert resp.status_code == 200
    assert resp.json()["state"] == "stopped"
    assert svc["terminate"] == [1.0]           # self exits after responding
    assert not service_control.pid_path().exists()


def test_stop_other_managed_process(client, svc, monkeypatch):
    service_control.write_pid(999999)
    monkeypatch.setattr(service_control, "pid_alive", lambda pid: True)
    resp = client.post("/api/v1/service/stop")
    assert resp.status_code == 200
    assert svc["kill"] == [999999]             # not self -> direct kill


def test_stop_stale_pidfile(client, svc):
    service_control.write_pid(999999)          # dead pid
    resp = client.post("/api/v1/service/stop")
    assert resp.json()["state"] == "stopped"
    assert not service_control.pid_path().exists()


def test_start_cold(client, svc):
    resp = client.post("/api/v1/service/start", json={"append": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "running"
    assert body["pid"] == 4242
    assert body["previous_pid"] is None
    assert svc["spawn"] == [(True, None)]


def test_start_restart_self(client, svc):
    service_control.write_pid(os.getpid())
    resp = client.post("/api/v1/service/start", json={})
    body = resp.json()
    assert body["state"] == "running"
    assert body["pid"] == 4242
    assert body["previous_pid"] == os.getpid()
    # child waits for self to exit; self terminates after responding
    assert svc["spawn"] == [(False, os.getpid())]
    assert svc["terminate"] == [1.0]


def test_start_restart_other(client, svc, monkeypatch):
    service_control.write_pid(999999)
    monkeypatch.setattr(service_control, "pid_alive", lambda pid: True)
    resp = client.post("/api/v1/service/start")
    body = resp.json()
    assert body["previous_pid"] == 999999
    assert svc["spawn"] == [(False, 999999)]
    assert svc["kill"] == [999999]
    assert svc["terminate"] == []

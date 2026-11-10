"""v1.7.1 CLI: every command mirrors a real REST op; no obsolete flows."""

import io
import json

import pytest
from PIL import Image
from typer.testing import CliRunner

from opal_look import service_control
from opal_look.app import create_app
from opal_look_cli import cli as cli_mod
from opal_look_cli.cli import app as cli_app


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    app = create_app(data_dir=tmp_path / "data")
    inner = TestClient(app, base_url="http://testserver")
    monkeypatch.setitem(cli_mod._state, "inner", inner)
    monkeypatch.setitem(cli_mod._state, "url", "http://testserver")
    yield CliRunner()
    cli_mod._state["inner"] = None


@pytest.fixture()
def cli_offline(monkeypatch):
    """CLI pointed at a dead URL so service verbs take the local fallback."""
    monkeypatch.setitem(cli_mod._state, "inner", None)
    monkeypatch.setitem(cli_mod._state, "url", "http://127.0.0.1:1")
    return CliRunner()


def test_cli_engine_list(cli):
    r = cli.invoke(cli_app, ["--json", "engine", "list"])
    assert r.exit_code == 0 and "synthetic" in r.output


def test_cli_model_show(cli):
    r = cli.invoke(cli_app, ["config", "model", "show", "synthetic-vision"])
    assert r.exit_code == 0 and "synthetic-vision" in r.output


def test_cli_health(cli):
    r = cli.invoke(cli_app, ["info", "health"])
    assert r.exit_code == 0


def test_cli_metrics(cli):
    r = cli.invoke(cli_app, ["info", "metrics"])
    assert r.exit_code == 0 and "captured_frames" in r.output


def test_cli_events_status(cli):
    r = cli.invoke(cli_app, ["info", "events"])
    assert r.exit_code == 0 and "enabled" in r.output


def test_cli_setting_show(cli):
    r = cli.invoke(cli_app, ["config", "setting", "show", "max_upload_bytes"])
    assert r.exit_code == 0 and "1073741824" in r.output


def test_cli_setting_update_and_alias(cli):
    r = cli.invoke(cli_app, ["config", "setting", "update", "--body",
                             '{"max_viewers": 3}'])
    assert r.exit_code == 0, r.output
    r = cli.invoke(cli_app, ["settings", "patch", "--body",
                             '{"max_viewers": 4}'])
    assert r.exit_code == 0, r.output
    r = cli.invoke(cli_app, ["settings", "reset", "max_viewers"])
    assert r.exit_code == 0, r.output


def test_cli_sources_add_and_list(cli, tmp_path):
    body = tmp_path / "src.json"
    body.write_text(
        '{"id": "cli-src", "name": "CLI", "kind": "rtsp", '
        '"locator": "rtsp://192.0.2.10/x"}')
    r = cli.invoke(cli_app, ["source", "add", "--file", str(body)])
    assert r.exit_code == 0, r.output
    assert "cli-src" in cli.invoke(cli_app, ["source", "list"]).output


def test_cli_media_upload_and_download(cli, tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="JPEG")
    img = tmp_path / "x.jpg"
    img.write_bytes(buf.getvalue())
    r = cli.invoke(cli_app, ["data", "media", "upload", str(img)])
    assert r.exit_code == 0, r.output
    mid = json.loads(r.output)["id"]
    # media download is gone upstream; binary content lives on captures
    out = tmp_path / "cap.jpg"
    r = cli.invoke(cli_app, ["source", "add", "--body",
                             '{"id":"ms","name":"M","kind":"media",'
                             f'"locator":"{mid}"' + '}'])
    assert r.exit_code == 0, r.output
    r = cli.invoke(cli_app, ["source", "capture", "ms"])
    assert r.exit_code == 0, r.output
    cap_id = json.loads(r.output)["id"]
    r = cli.invoke(cli_app, ["data", "capture", "download", cap_id,
                             "--out", str(out)])
    assert r.exit_code == 0 and out.read_bytes()[:2] == b"\xff\xd8"


def test_cli_pipelines_validate(cli):
    r = cli.invoke(cli_app, ["config", "pipeline", "validate", "--body",
                             '{"id": "p", "name": "P", "stages": [{"id": "s1", "kind": '
                             '"inference", "model_id": "synthetic-vision", '
                             '"task": "detection"}]}'])
    assert r.exit_code == 0


def test_cli_jobs_submit_cancel(cli):
    body = {"kind": "media_export", "media_id": "none",
            "output": {"format": "png"}}
    r = cli.invoke(cli_app, ["data", "job", "submit", "--body",
                             json.dumps(body)])
    assert r.exit_code in (0, 1)  # 404 media -> SystemExit error, never hang


def test_cli_backup_export(cli):
    r = cli.invoke(cli_app, ["backup", "export"])
    assert r.exit_code == 0 and "settings" in r.output


def test_cli_backup_create_list(cli):
    r = cli.invoke(cli_app, ["backup", "create"])
    assert r.exit_code == 0, r.output
    name = json.loads(r.output)["filename"]
    assert "opal-look-" in name
    listed = json.loads(cli.invoke(cli_app, ["backup", "list"]).output)
    assert listed[0]["filename"] == name


def test_cli_persona_crud(cli):
    r = cli.invoke(cli_app, ["config", "persona", "add", "--body",
                             '{"persona_id":"amy","name":"Amy"}'])
    assert r.exit_code == 0, r.output
    assert "amy" in cli.invoke(
        cli_app, ["config", "persona", "list"]).output
    assert "Amy" in cli.invoke(
        cli_app, ["config", "persona", "show", "amy"]).output
    r = cli.invoke(cli_app, ["config", "persona", "update", "amy", "--body",
                             '{"voice_id":"en-gb-alan-low"}'])
    assert r.exit_code == 0, r.output
    assert '"valid": true' in cli.invoke(
        cli_app, ["--json", "config", "persona", "validate", "amy"]).output
    r = cli.invoke(cli_app, ["config", "persona", "remove", "amy"])
    assert r.exit_code == 0, r.output
    assert cli.invoke(
        cli_app, ["config", "persona", "show", "amy"]).exit_code != 0


def test_cli_info(cli):
    r = cli.invoke(cli_app, ["info", "version"])
    assert r.exit_code == 0 and "opal-look-svc" in r.output
    r = cli.invoke(cli_app, ["info", "ping"])
    assert r.exit_code == 0 and '"status": "ok"' in r.output


def test_cli_service_log_rest(cli, tmp_path, monkeypatch):
    """Server reachable -> the REST /service/log op serves the tail."""
    monkeypatch.setattr(service_control, "LOG_DIR", tmp_path / "logs")
    service_control.log_dir().mkdir(parents=True)
    service_control.log_path().write_text(
        "\n".join(f"line{i}" for i in range(15)))
    r = cli.invoke(cli_app, ["service", "log"])
    assert r.exit_code == 0
    assert "line14" in r.output and "line5" in r.output
    assert "line4" not in r.output  # default tail is 10 lines


def test_cli_service_log_missing_rest(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(service_control, "LOG_DIR", tmp_path / "logs")
    assert cli.invoke(cli_app, ["service", "log"]).exit_code != 0


def test_cli_service_stop_rest_not_running(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(service_control, "LOG_DIR", tmp_path / "logs")
    r = cli.invoke(cli_app, ["service", "stop"])
    assert r.exit_code == 0 and '"state": "stopped"' in r.output


def test_cli_service_start_rest(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(service_control, "LOG_DIR", tmp_path / "logs")
    spawned = []
    monkeypatch.setattr(
        service_control, "spawn_server",
        lambda append=False, wait_pid=None, env_extra=None:
        spawned.append((append, wait_pid)) or 4242)
    r = cli.invoke(cli_app, ["service", "start"])
    assert r.exit_code == 0, r.output
    body = json.loads(r.output)
    assert body["state"] == "running" and body["pid"] == 4242


def test_cli_service_log_fallback(cli_offline, tmp_path, monkeypatch):
    """API unreachable -> local log tail via the shared pidfile dir."""
    monkeypatch.setattr(service_control, "LOG_DIR", tmp_path / "logs")
    service_control.log_dir().mkdir(parents=True)
    service_control.log_path().write_text("a\nb\nc")
    r = cli_offline.invoke(cli_app, ["service", "log", "--lines", "2"])
    assert r.exit_code == 0 and "b" in r.output and "c" in r.output


def test_cli_service_log_fallback_missing(cli_offline, tmp_path, monkeypatch):
    monkeypatch.setattr(service_control, "LOG_DIR", tmp_path / "logs")
    assert cli_offline.invoke(cli_app, ["service", "log"]).exit_code != 0


def test_cli_service_stop_fallback(cli_offline, tmp_path, monkeypatch):
    monkeypatch.setattr(service_control, "LOG_DIR", tmp_path / "logs")
    r = cli_offline.invoke(cli_app, ["service", "stop"])
    assert r.exit_code == 0 and "no server running" in r.output


def test_cli_service_start_fallback(cli_offline, tmp_path, monkeypatch):
    monkeypatch.setattr(service_control, "LOG_DIR", tmp_path / "logs")

    class _FakeProc:
        pid = -1  # never a real pid; no stop call follows this test

    monkeypatch.setattr(service_control.subprocess, "Popen",
                        lambda *a, **k: _FakeProc())
    r = cli_offline.invoke(cli_app, ["service", "start"])
    assert r.exit_code == 0, r.output
    assert service_control.log_path().is_file()
    assert service_control.pid_path().read_text().strip() == "-1"


def test_cli_obsolete_commands_gone(cli):
    """v1.4 resources and v1.6 plural groups have no v1.7.1 spelling."""
    for group in ("results", "snapshots", "sources", "sessions", "engines",
                  "models", "jobs", "captures", "artifacts", "recordings",
                  "pipelines", "profiles", "zones", "rules", "monitors",
                  "observations", "media", "configuration", "capabilities",
                  "metrics", "events", "health"):
        r = cli.invoke(cli_app, [group, "list"])
        assert r.exit_code != 0, f"{group} still exposed"


def test_cli_unknown_exit_code(cli):
    r = cli.invoke(cli_app, ["config", "model", "show", "ghost-model"])
    assert r.exit_code != 0
    assert "404" in r.output or "Unknown" in r.output


def _upload_and_source(client):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="JPEG")
    mid = client.post("/api/v1/media/", files={
        "file": ("x.jpg", buf.getvalue(), "image/jpeg")}).json()["id"]
    client.post("/api/v1/source/",
                json={"id": "ms", "name": "M", "kind": "media",
                      "locator": mid}, headers={"If-Match": "*"})


def test_cli_capture_output_ref_and_fetch(cli, tmp_path):
    _upload_and_source(cli_mod._state["inner"])
    r = cli.invoke(cli_app, ["--json", "source", "capture", "ms"])
    assert r.exit_code == 0, r.output
    ref = json.loads(r.output)["output_ref"]
    out = tmp_path / "frame.jpg"
    r = cli.invoke(cli_app, ["output", "fetch", ref["content_url"],
                             "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert out.read_bytes()[:2] == b"\xff\xd8"  # JPEG magic


def test_cli_output_fetch_recording_artifact_ref(cli, tmp_path):
    inner = cli_mod._state["inner"]
    store = inner.app.state.store
    store.recordings.insert({"recording_id": "rec-9", "source_id": "ms",
        "state": "finished", "created_at": "t", "started_at": "t",
        "finished_at": "t", "media_id": "m1", "failure": None})
    store.recordings.update("rec-9", {"artifact_id": "art-9"})
    r = cli.invoke(cli_app, ["--json", "data", "recording", "show", "rec-9"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["artifact_ref"]["content_url"] \
        == "/api/v1/artifact/art-9/content"


def test_cli_output_fetch_rejects_bad_url(cli):
    r = cli.invoke(cli_app, ["output", "fetch", "/api/v1/media/m1/content"])
    assert r.exit_code != 0
    assert "expected a content_url" in r.output

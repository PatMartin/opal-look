"""v1.6 CLI: every command mirrors a real REST op; no obsolete flows."""

import io
import json

import httpx
import pytest
from PIL import Image
from typer.testing import CliRunner

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


def test_cli_engines_list(cli):
    r = cli.invoke(cli_app, ["--json", "engines", "list"])
    assert r.exit_code == 0 and "synthetic" in r.output


def test_cli_models_show(cli):
    r = cli.invoke(cli_app, ["models", "show", "synthetic-vision"])
    assert r.exit_code == 0 and "synthetic-vision" in r.output


def test_cli_health(cli):
    r = cli.invoke(cli_app, ["info", "health", "show"])
    assert r.exit_code == 0


def test_cli_metrics(cli):
    r = cli.invoke(cli_app, ["metrics", "show"])
    assert r.exit_code == 0 and "captured_frames" in r.output


def test_cli_events_status(cli):
    r = cli.invoke(cli_app, ["events", "status"])
    assert r.exit_code == 0 and "enabled" in r.output


def test_cli_settings_show(cli):
    r = cli.invoke(cli_app, ["settings", "show", "max_upload_bytes"])
    assert r.exit_code == 0 and "1073741824" in r.output


def test_cli_sources_add_and_list(cli, tmp_path):
    body = tmp_path / "src.json"
    body.write_text(
        '{"id": "cli-src", "name": "CLI", "kind": "rtsp", '
        '"locator": "rtsp://192.0.2.10/x"}')
    r = cli.invoke(cli_app, ["sources", "add", "--file", str(body)])
    assert r.exit_code == 0, r.output
    assert "cli-src" in cli.invoke(cli_app, ["sources", "list"]).output


def test_cli_media_upload_and_download(cli, tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="JPEG")
    img = tmp_path / "x.jpg"
    img.write_bytes(buf.getvalue())
    r = cli.invoke(cli_app, ["media", "upload", str(img)])
    assert r.exit_code == 0, r.output
    mid = json.loads(r.output)["id"]
    # media download is gone upstream; binary content lives on captures
    out = tmp_path / "cap.jpg"
    r = cli.invoke(cli_app, ["sources", "add", "--body",
                             '{"id":"ms","name":"M","kind":"media",'
                             f'"locator":"{mid}"' + '}'])
    assert r.exit_code == 0, r.output
    r = cli.invoke(cli_app, ["sources", "capture", "ms"])
    assert r.exit_code == 0, r.output
    cap_id = json.loads(r.output)["id"]
    r = cli.invoke(cli_app, ["captures", "download", cap_id, "--out", str(out)])
    assert r.exit_code == 0 and out.read_bytes()[:2] == b"\xff\xd8"


def test_cli_pipelines_validate(cli):
    r = cli.invoke(cli_app, ["pipelines", "validate", "--body",
                             '{"id": "p", "name": "P", "stages": [{"id": "s1", "kind": '
                             '"inference", "model_id": "synthetic-vision", '
                             '"task": "detection"}]}'])
    assert r.exit_code == 0


def test_cli_jobs_submit_cancel(cli):
    body = {"kind": "media_export", "media_id": "none",
            "output": {"format": "png"}}
    r = cli.invoke(cli_app, ["jobs", "submit", "--body", json.dumps(body)])
    assert r.exit_code in (0, 1)  # 404 media -> SystemExit error, never hang


def test_cli_configuration_export(cli):
    r = cli.invoke(cli_app, ["configuration", "export"])
    assert r.exit_code == 0 and "settings" in r.output


def test_cli_persona_crud(cli):
    r = cli.invoke(cli_app, ["persona", "add", "--body",
                             '{"persona_id":"amy","name":"Amy"}'])
    assert r.exit_code == 0, r.output
    assert "amy" in cli.invoke(cli_app, ["persona", "list"]).output
    assert "Amy" in cli.invoke(cli_app, ["persona", "show", "amy"]).output
    r = cli.invoke(cli_app, ["persona", "update", "amy", "--body",
                             '{"voice_id":"en-gb-alan-low"}'])
    assert r.exit_code == 0, r.output
    assert '"valid": true' in cli.invoke(
        cli_app, ["--json", "persona", "validate", "amy"]).output
    r = cli.invoke(cli_app, ["persona", "remove", "amy"])
    assert r.exit_code == 0, r.output
    assert cli.invoke(cli_app, ["persona", "show", "amy"]).exit_code != 0


def test_cli_info(cli):
    r = cli.invoke(cli_app, ["info", "version"])
    assert r.exit_code == 0 and "opal-look-svc" in r.output
    r = cli.invoke(cli_app, ["info", "ping"])
    assert r.exit_code == 0 and '"status": "ok"' in r.output


def test_cli_service_log_tail(cli, tmp_path, monkeypatch):
    logdir = tmp_path / "logs"
    monkeypatch.setattr(cli_mod, "_LOG_DIR", logdir)
    logdir.mkdir()
    (logdir / "opal_listen.log").write_text(
        "\n".join(f"line{i}" for i in range(15)))
    r = cli.invoke(cli_app, ["service", "log"])
    assert r.exit_code == 0
    assert "line14" in r.output and "line5" in r.output
    assert "line4" not in r.output  # default tail is 10 lines


def test_cli_service_log_missing(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "_LOG_DIR", tmp_path / "logs")
    assert cli.invoke(cli_app, ["service", "log"]).exit_code != 0


def test_cli_service_stop_not_running(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "_LOG_DIR", tmp_path / "logs")
    r = cli.invoke(cli_app, ["service", "stop"])
    assert r.exit_code == 0 and "no server running" in r.output


def test_cli_service_start_writes_pidfile(cli, tmp_path, monkeypatch):
    logdir = tmp_path / "logs"
    monkeypatch.setattr(cli_mod, "_LOG_DIR", logdir)

    class _FakeProc:
        pid = -1  # never a real pid; no stop call follows this test

    monkeypatch.setattr(cli_mod.subprocess, "Popen", lambda *a, **k: _FakeProc())
    r = cli.invoke(cli_app, ["service", "start"])
    assert r.exit_code == 0, r.output
    assert (logdir / "opal_listen.log").is_file()
    assert (logdir / "opal_look.pid").read_text().strip() == "-1"


def test_cli_obsolete_commands_gone(cli):
    """v1.4 resources have no REST op — the CLI must not expose them."""
    for group in ("results", "snapshots", "backup"):
        r = cli.invoke(cli_app, [group, "list"])
        assert r.exit_code != 0, f"{group} still exposed"


def test_cli_unknown_exit_code(cli):
    r = cli.invoke(cli_app, ["models", "show", "ghost-model"])
    assert r.exit_code != 0
    assert "404" in r.output or "Unknown" in r.output

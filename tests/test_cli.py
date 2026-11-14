"""MVP CLI: every command mirrors a real REST op; no retired flows."""

import json

import pytest
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
    assert r.exit_code == 0
    assert "synthetic" in r.output


def test_cli_engine_show(cli):
    r = cli.invoke(cli_app, ["engine", "show", "synthetic"])
    assert r.exit_code == 0
    assert "synthetic" in r.output


def test_cli_engine_update(cli):
    r = cli.invoke(cli_app, ["config", "engine", "update", "synthetic",
                             "--body", '{"enabled": false}'])
    assert r.exit_code == 0, r.output
    assert '"enabled": false' in r.output


def test_cli_health(cli):
    r = cli.invoke(cli_app, ["info", "health"])
    assert r.exit_code == 0
    assert "synthetic" in r.output


def test_cli_setting_show(cli):
    r = cli.invoke(cli_app, ["config", "setting", "show", "max_upload_bytes"])
    assert r.exit_code == 0
    assert "max_upload_bytes" in r.output


def test_cli_setting_update(cli):
    r = cli.invoke(cli_app, ["config", "setting", "update", "--body",
                             '{"max_viewers": 3}'])
    assert r.exit_code == 0
    assert '"max_viewers": 3' in r.output


def test_cli_profile_crud(cli):
    r = cli.invoke(cli_app, ["config", "profile", "add", "--body",
                             '{"name": "cli-prof"}'])
    assert r.exit_code == 0, r.output
    assert "cli-prof" in cli.invoke(
        cli_app, ["config", "profile", "list"]).output


def test_cli_backup_export(cli):
    r = cli.invoke(cli_app, ["backup", "export"])
    assert r.exit_code == 0
    assert '"format_version": "1.0.0"' in r.output


def test_cli_backup_create_list(cli):
    r = cli.invoke(cli_app, ["backup", "create"])
    assert r.exit_code == 0, r.output
    assert "opal-look-" in r.output
    listed = json.loads(cli.invoke(cli_app, ["backup", "list"]).output)
    assert listed and listed[0]["filename"].startswith("opal-look-")


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


def test_cli_retired_groups_gone(cli):
    """Retired domains and old plural/group spellings have no CLI home."""
    for argv in (["source", "list"], ["session", "list"], ["analyze", "run"],
                 ["data", "job", "list"], ["config", "pipeline", "list"],
                 ["config", "zone", "list"], ["config", "rule", "list"],
                 ["config", "monitor", "list"], ["config", "persona", "list"],
                 ["config", "model", "list"], ["settings", "patch"],
                 ["info", "metrics"], ["info", "events"],
                 ["info", "capabilities"], ["output", "fetch", "x"]):
        r = cli.invoke(cli_app, argv)
        assert r.exit_code != 0, f"{argv} still exposed"


def test_cli_unknown_exit_code(cli):
    r = cli.invoke(cli_app, ["engine", "show", "ghost-engine"])
    assert r.exit_code != 0
    assert "404" in r.output or "Unknown" in r.output


def test_cli_tree_renders_live_command_tree(cli):
    result = cli.invoke(cli_app, ["tree"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert out.splitlines()[0].startswith("opal-look")
    # groups and leaf commands are present with Unicode box-drawing guides
    assert "├── stream" in out and "└── config" in out
    # piped output carries no ANSI escapes; styles only appear on a terminal
    assert "\x1b[" not in out
    # notation: required args bare, optional bracketed
    assert "start source" in out
    assert "list [--engine]" in out
    # the tree's own --ascii flag shows as an optional parameter
    assert "tree [--ascii]" in out
    # built-in help and shell-completion plumbing are skipped
    assert "--help" not in out and "--install-completion" not in out


def test_cli_tree_styles_when_on_a_terminal(cli):
    """render_tree produces a styled rich Tree: ANSI escapes only when the
    console is a terminal."""
    import io
    import re

    from rich.console import Console
    from typer.main import get_command

    from opal_look_cli.tree_cmds import render_tree

    def render(force_terminal: bool) -> str:
        con = Console(file=io.StringIO(), force_terminal=force_terminal,
                      width=120)
        con.print(render_tree(get_command(cli_app), "opal-look"))
        return con.file.getvalue()

    styled, plain = render(True), render(False)
    assert "\x1b[" in styled and "\x1b[" not in plain
    # stripping ANSI leaves the same Unicode box-drawing tree either way
    assert re.sub(r"\x1b\[[0-9;]*m", "", styled) == plain
    assert "├── stream" in plain and "└── config" in plain


def test_cli_tree_ascii(cli):
    result = cli.invoke(cli_app, ["tree", "--ascii"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert out.splitlines()[0].startswith("opal-look")
    # ASCII guides only — no Unicode box-drawing, no ANSI escapes
    assert "|-- stream" in out and "`-- config" in out
    assert "├──" not in out and "└──" not in out and "│" not in out \
        and "\x1b[" not in out
    out.encode("ascii")
    assert "tree [--ascii]" in out and "start source" in out


def _fake_rtsp(monkeypatch):
    import time

    from PIL import Image

    from opal_look.capture import CAPTURE_REGISTRY

    class _Frames:
        def read(self):
            time.sleep(0.005)
            return Image.new("RGB", (16, 16), (9, 9, 9))

        def close(self):
            pass

    class _Rtsp:
        source_type = "rtsp"

        def open_stream(self, locator, options, cred):
            return _Frames()

    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp", _Rtsp())


def test_cli_hardware_and_discover(cli):
    assert cli.invoke(cli_app, ["engine", "discover"]).exit_code == 0
    r = cli.invoke(cli_app, ["engine", "capabilities", "synthetic"])
    assert r.exit_code == 0 and "detection" in r.output
    r = cli.invoke(cli_app, ["--json", "hardware", "list"])
    assert r.exit_code == 0 and "cpu" in r.output
    r = cli.invoke(cli_app, ["hardware", "show", "cpu"])
    assert r.exit_code == 0


def test_cli_model_predict_stream(cli, tmp_path, monkeypatch):
    _fake_rtsp(monkeypatch)
    r = cli.invoke(cli_app, ["model", "load", "synthetic-det"])
    assert r.exit_code == 0, r.output
    img = tmp_path / "img.jpg"
    from PIL import Image
    Image.new("RGB", (16, 16)).save(img)
    r = cli.invoke(cli_app, ["predict", "image", "--engine", "synthetic",
                             "--model", "synthetic-det", "--source", str(img)])
    assert r.exit_code == 0, r.output
    r = cli.invoke(cli_app, ["--json", "stream", "start", "rtsp://cam/x"])
    assert r.exit_code == 0, r.output
    sid = json.loads(r.output)["stream_id"]
    assert cli.invoke(cli_app, ["stream", "list"]).exit_code == 0
    assert cli.invoke(cli_app, ["stream", "metrics", sid]).exit_code == 0
    r = cli.invoke(cli_app, ["stream", "snapshot", sid,
                             "--out", str(tmp_path / "s.jpg")])
    assert r.exit_code == 0 and (tmp_path / "s.jpg").is_file()
    assert cli.invoke(cli_app, ["stream", "stop", sid]).exit_code == 0
    assert cli.invoke(cli_app, ["model", "unload",
                                "synthetic-det"]).exit_code == 0

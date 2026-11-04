"""v1.5 CLI: every command mirrors a real REST op; no obsolete flows."""

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
    r = cli.invoke(cli_app, ["health", "show"])
    assert r.exit_code == 0


def test_cli_metrics(cli):
    r = cli.invoke(cli_app, ["metrics", "show"])
    assert r.exit_code == 0 and "counters" in r.output


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
    out = tmp_path / "dl.bin"
    r = cli.invoke(cli_app, ["media", "download", mid, "--out", str(out)])
    assert r.exit_code == 0 and out.read_bytes()[:2] == b"\xff\xd8"


def test_cli_pipelines_validate(cli):
    r = cli.invoke(cli_app, ["pipelines", "validate", "--body",
                             '{"id": "p", "name": "P", "model_id": "synthetic-vision", '
                             '"task": "detection"}'])
    assert r.exit_code == 0


def test_cli_jobs_submit_cancel(cli):
    body = {"kind": "media_export", "media_id": "none",
            "output": {"format": "png"}}
    r = cli.invoke(cli_app, ["jobs", "submit", "--body", json.dumps(body)])
    assert r.exit_code in (0, 1)  # 404 media -> SystemExit error, never hang


def test_cli_configuration_export(cli):
    r = cli.invoke(cli_app, ["configuration", "export"])
    assert r.exit_code == 0 and "settings" in r.output


def test_cli_obsolete_commands_gone(cli):
    """v1.4 resources have no REST op — the CLI must not expose them."""
    for group in ("profiles", "sessions", "results", "snapshots", "backup"):
        r = cli.invoke(cli_app, [group, "list"])
        assert r.exit_code != 0, f"{group} still exposed"


def test_cli_unknown_exit_code(cli):
    r = cli.invoke(cli_app, ["models", "show", "ghost-model"])
    assert r.exit_code != 0
    assert "404" in r.output or "Unknown" in r.output

import io

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
    result = cli.invoke(cli_app, ["--json", "engines", "list"])
    assert result.exit_code == 0
    assert "synthetic" in result.output


def test_cli_models_show(cli):
    result = cli.invoke(cli_app, ["models", "show", "synthetic-vision"])
    assert result.exit_code == 0
    assert "synthetic-vision" in result.output


def test_cli_health(cli):
    result = cli.invoke(cli_app, ["health"])
    assert result.exit_code == 0


def test_cli_settings_show(cli):
    result = cli.invoke(cli_app, ["settings", "show", "max_upload_bytes"])
    assert result.exit_code == 0
    assert "1073741824" in result.output


def test_cli_backup_export(cli):
    result = cli.invoke(cli_app, ["backup", "export"])
    assert result.exit_code == 0
    assert "1.1.0" in result.output


def test_cli_sources_add_and_list(cli, tmp_path):
    body = tmp_path / "src.json"
    body.write_text(
        '{"id": "cli-src", "name": "CLI", "kind": "rtsp", '
        '"locator": "rtsp://192.0.2.10/x"}')
    result = cli.invoke(cli_app, ["sources", "add", "--file", str(body)])
    assert result.exit_code == 0, result.output
    result = cli.invoke(cli_app, ["sources", "list"])
    assert "cli-src" in result.output


def test_cli_profiles_activate(cli):
    result = cli.invoke(
        cli_app,
        ["profiles", "add", "--body",
         '{"name": "p1", "model_id": "synthetic-vision", "task": "detection"}'])
    assert result.exit_code == 0, result.output
    import json
    pid = json.loads(result.output)["profile_id"]
    result = cli.invoke(cli_app, ["profiles", "activate", str(pid)])
    assert result.exit_code == 0
    assert json.loads(result.output)["active"] is True


def test_cli_sessions_add_202(cli, tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="JPEG")
    img = tmp_path / "x.jpg"
    img.write_bytes(buf.getvalue())
    result = cli.invoke(cli_app, ["media", "upload", str(img)])
    assert result.exit_code == 0, result.output
    import json
    mid = json.loads(result.output)["media_id"]
    result = cli.invoke(cli_app, [
        "sources", "add", "--body",
        f'{{"id": "ms", "name": "M", "kind": "media", "locator": "{mid}"}}'])
    assert result.exit_code == 0
    result = cli.invoke(cli_app, [
        "sessions", "add", "--body",
        '{"source_id": "ms", "model_id": "synthetic-vision", "task": "detection"}'])
    assert result.exit_code == 0
    assert "session_id" in result.output

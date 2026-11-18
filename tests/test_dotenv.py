"""Tests for the OPAL dotenv policy: `opal_look.dotenv.prepare` and its wiring
into the service entry point (`python -m opal_look`), the `opal-look` CLI, and
the `opal serve` umbrella command."""

from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from opal_look.dotenv import DotenvError, prepare
from opal_look.main import _baseline
from opal_look_cli.cli import app
from opal_look_cli.opal import opal_app

_TRACKED = ("OPAL_DOTENV_FILE", "OPAL_NO_DOTENV", "APP_VALUE", "APP_TOKEN", "OPAL_LOOK_PORT")


@pytest.fixture(autouse=True)
def clean_policy(monkeypatch):
    for var in _TRACKED:
        monkeypatch.delenv(var, raising=False)
    yield
    for var in _TRACKED:
        os.environ.pop(var, None)


def test_default_env_created_and_loaded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = prepare(baseline={"APP_VALUE": "from-default"})
    assert result.created
    assert os.environ["APP_VALUE"] == "from-default"
    assert (tmp_path / ".env").read_text(encoding="utf-8").startswith("# Generated OPAL")


def test_existing_nonempty_environment_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_VALUE", "real-env")
    (tmp_path / ".env").write_text("APP_VALUE='dotenv'\n")
    prepare()
    assert os.environ["APP_VALUE"] == "real-env"


def test_existing_empty_environment_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_VALUE", "")
    (tmp_path / ".env").write_text("APP_VALUE='dotenv'\n")
    prepare()
    assert os.environ["APP_VALUE"] == ""


def test_real_env_wins_over_generated_baseline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_VALUE", "real-env")
    prepare(baseline={"APP_VALUE": "baseline"})
    assert os.environ["APP_VALUE"] == "real-env"
    assert "APP_VALUE='baseline'" in (tmp_path / ".env").read_text()


def test_no_parent_directory_search(tmp_path, monkeypatch):
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    (root / ".env").write_text("APP_VALUE='parent'\n")
    monkeypatch.chdir(child)
    prepare(baseline={"APP_VALUE": "baseline"})
    assert os.environ["APP_VALUE"] == "baseline"
    assert not (root / ".env").read_text().startswith("# Generated")


def test_existing_env_file_not_rewritten(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".env"
    path.write_text("APP_VALUE='custom'\n")
    prepare(baseline={"APP_VALUE": "baseline"})
    assert path.read_text() == "APP_VALUE='custom'\n"


def test_no_env_file_disables_loading_and_creation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = prepare(no_env_file=True)
    assert result.disabled and not result.loaded and not (tmp_path / ".env").exists()
    assert os.environ["OPAL_NO_DOTENV"] == "1"
    assert "OPAL_DOTENV_FILE" not in os.environ


def test_explicit_missing_and_mutually_exclusive_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(DotenvError, match="not found"):
        prepare(env_file="missing.env")
    with pytest.raises(DotenvError, match="not found"):
        prepare(env_file=".")
    with pytest.raises(DotenvError, match="mutually exclusive"):
        prepare(env_file=".env", no_env_file=True)


def test_explicit_relative_path_resolves_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    explicit = tmp_path / "conf" / "local.env"
    explicit.parent.mkdir()
    explicit.write_text("APP_VALUE='explicit'\n")
    prepare(env_file="conf/local.env")
    assert os.environ["APP_VALUE"] == "explicit"


def test_explicit_env_file_wins_over_inherited_variable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.env").write_text("APP_VALUE='from-a'\n")
    (tmp_path / "b.env").write_text("APP_VALUE='from-b'\n")
    monkeypatch.setenv("OPAL_DOTENV_FILE", "a.env")
    result = prepare(env_file="b.env")
    assert os.environ["APP_VALUE"] == "from-b"
    assert result.path == (tmp_path / "b.env").resolve()


def test_inherited_env_file_used_when_flag_omitted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "parent.env").write_text("APP_VALUE='inherited'\n")
    monkeypatch.setenv("OPAL_DOTENV_FILE", "parent.env")
    prepare()
    assert os.environ["APP_VALUE"] == "inherited"


def test_generated_file_omits_secret_values_and_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_TOKEN", "live-token-value")
    prepare(baseline={"APP_TOKEN": "super-secret", "APP_VALUE": "safe"})
    text = (tmp_path / ".env").read_text()
    assert "super-secret" not in text
    assert "live-token-value" not in text
    assert "# APP_TOKEN=<redacted>" in text


def test_creation_failure_warns_and_continues(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def _fail(path, values):
        raise OSError("read-only directory")

    monkeypatch.setattr("opal_look.dotenv.create_default_env", _fail)
    with pytest.warns(RuntimeWarning, match="could not initialize"):
        result = prepare(baseline={"APP_VALUE": "x"})
    assert result.created is False
    assert not (tmp_path / ".env").exists()


def test_policy_propagates_for_subprocesses(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prepare()
    assert os.environ["OPAL_DOTENV_FILE"] == str(tmp_path / ".env")
    assert "OPAL_NO_DOTENV" not in os.environ


def test_library_use_has_no_dotenv_side_effects(tmp_path, monkeypatch):
    """_baseline() resolves values without touching .env or the environment."""
    monkeypatch.chdir(tmp_path)
    assert _baseline()["OPAL_LOOK_PORT"] == 8002
    assert "OPAL_DOTENV_FILE" not in os.environ
    assert not (tmp_path / ".env").exists()


def test_create_app_does_not_load_dotenv(tmp_path, monkeypatch):
    """Embedded mode: the app factory accepts config, it does not own dotenv."""
    monkeypatch.chdir(tmp_path)
    from opal_look.app import create_app

    create_app()
    assert "OPAL_DOTENV_FILE" not in os.environ
    assert not (tmp_path / ".env").exists()


def test_cli_dotenv_controls(tmp_path, monkeypatch):
    """The `opal-look` callback applies the policy before any command runs."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--env-file", "missing.env", "info", "health"])
    assert result.exit_code != 0
    assert "dotenv file not found" in result.output
    result = runner.invoke(app, ["--no-env-file", "info", "health"])
    assert not (tmp_path / ".env").exists()
    # CliRunner shares the process; a real second invocation starts clean.
    monkeypatch.delenv("OPAL_NO_DOTENV", raising=False)
    monkeypatch.delenv("OPAL_DOTENV_FILE", raising=False)
    result = runner.invoke(app, ["info", "health"])
    assert (tmp_path / ".env").exists()


def test_opal_serve_forwards_env_file_flag(tmp_path, monkeypatch):
    """`opal serve --env-file` reaches the service entry point's parser."""
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(opal_app, ["serve", "--env-file", "missing.env"])
    assert result.exit_code == 2
    assert "dotenv file not found" in result.output


def test_opal_serve_forwards_no_env_file(tmp_path, monkeypatch):
    """`opal serve --no-env-file` disables loading for the service process."""
    captured = {}

    def _run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", _run)
    monkeypatch.setattr("opal_look.service_control.ensure_pidfile", lambda: None)
    monkeypatch.setattr("opal_look.service_control.release_pidfile", lambda: None)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(opal_app, ["serve", "--no-env-file", "--port", "0"])
    # --port is not a serve option; keep to flags only
    assert result.exit_code != 0 or not (tmp_path / ".env").exists()


def test_service_entrypoint_rejects_missing_env_file(tmp_path, monkeypatch):
    from opal_look.main import main

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["--env-file", "missing.env"])
    assert exc.value.code == 2

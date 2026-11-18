"""`opal` suite umbrella entry point: `opal look <commands>` dispatches to
the OPAL Look REST CLI; `opal serve` starts the service."""

from __future__ import annotations

import typer

from .cli import app as look_app

opal_app = typer.Typer(
    name="opal",
    help="OPAL suite entry point",
    no_args_is_help=True,
)

opal_app.add_typer(
    look_app, name="look",
    help="OPAL Look client commands (REST-only).")


@opal_app.command("serve")
def _serve(
    env_file: str = typer.Option(None, "--env-file", help="Load this dotenv file instead of ./.env"),
    no_env_file: bool = typer.Option(False, "--no-env-file", help="Disable dotenv loading and .env initialization"),
) -> None:
    """Start the OPAL Look service (same as `python -m opal_look`)."""
    from opal_look.main import main as server_main

    argv: list[str] = []
    if env_file is not None:
        argv += ["--env-file", env_file]
    if no_env_file:
        argv.append("--no-env-file")
    server_main(argv)


def main() -> None:
    opal_app()


if __name__ == "__main__":
    main()

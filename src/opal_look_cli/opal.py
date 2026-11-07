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
def _serve() -> None:
    """Start the OPAL Look service (same as `python -m opal_look`)."""
    from opal_look.main import main as server_main

    server_main()


def main() -> None:
    opal_app()


if __name__ == "__main__":
    main()

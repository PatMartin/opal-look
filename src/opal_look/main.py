"""`python -m opal_look` / `opal-look` entry point."""

from __future__ import annotations

import argparse
import os


def _baseline() -> dict[str, object]:
    from .settings import ServiceSettings

    values = {
        "OPAL_LOOK_HOST": "127.0.0.1",
        "OPAL_LOOK_PORT": 8002,
        "OPAL_LOOK_DATA_DIR": "data",
        "OPAL_LOOK_TOKEN": "<set-a-token>",
    }
    values.update({f"OPAL_LOOK_{key.upper()}": value for key, value in ServiceSettings().model_dump().items()})
    return values


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="opal-look service")
    parser.add_argument("--env-file")
    parser.add_argument("--no-env-file", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn

    from . import service_control
    from .dotenv import DotenvError, prepare

    try:
        prepare(env_file=args.env_file, no_env_file=args.no_env_file, baseline=_baseline())
    except DotenvError as exc:
        parser.error(str(exc))
    from .auth import assert_bind_allowed, env_token

    host = os.environ.get("OPAL_LOOK_HOST", "127.0.0.1")
    # Non-loopback deployments require bearer auth (v1.5 security boundary).
    assert_bind_allowed(host, env_token())
    # A restarted child waits for its predecessor to release the port.
    wait_pid = os.environ.get(service_control.WAIT_PID_ENV)
    if wait_pid and wait_pid.isdigit():
        service_control.wait_for_death(int(wait_pid))
    service_control.ensure_pidfile()
    try:
        uvicorn.run(
            "opal_look.app:create_app",
            factory=True,
            host=host,
            port=int(os.environ.get("OPAL_LOOK_PORT", "8002")),
        )
    finally:
        service_control.release_pidfile()


if __name__ == "__main__":
    main()

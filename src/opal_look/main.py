"""`python -m opal_look` / `opal-look` entry point."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    # .env supplies OPAL_LOOK_* env vars (never overrides real env).
    load_dotenv()

    from . import service_control
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
            port=int(os.environ.get("OPAL_LOOK_PORT", "8000")),
        )
    finally:
        service_control.release_pidfile()


if __name__ == "__main__":
    main()

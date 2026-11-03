"""`python -m opal_look` / `opal-look` entry point."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    from .auth import TOKEN_ENV, assert_bind_allowed, env_token

    host = os.environ.get("OPAL_LOOK_HOST", "127.0.0.1")
    # Non-loopback deployments require bearer auth (v1.5 security boundary).
    assert_bind_allowed(host, env_token())
    uvicorn.run(
        "opal_look.app:create_app",
        factory=True,
        host=host,
        port=int(os.environ.get("OPAL_LOOK_PORT", "8000")),
    )


if __name__ == "__main__":
    main()

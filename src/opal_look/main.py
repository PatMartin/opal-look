"""`python -m opal_look` / `opal-look` entry point."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "opal_look.app:create_app",
        factory=True,
        host=os.environ.get("OPAL_LOOK_HOST", "127.0.0.1"),
        port=int(os.environ.get("OPAL_LOOK_PORT", "8000")),
    )


if __name__ == "__main__":
    main()

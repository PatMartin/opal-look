"""Application factory."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from . import constants
from .access_log import AccessLogMiddleware
from .auth import BearerAuthMiddleware, env_token
from .correlation import CorrelationMiddleware
from .capture import load_capture_plugins
from .engines import ensure_engines, load_plugin_adapters
from .errors import register_error_handlers
from .framecache import FrameCache
from .routers import (
    backup, engines, hardware, health, models, predict, profiles, service,
    settings, streams,
)
from .store import Store


def default_data_dir() -> Path:
    return Path(os.environ.get("OPAL_LOOK_DATA_DIR", "data"))


def create_app(
    data_dir: Path | str | None = None,
    store: Store | None = None,
    auth_token: str | None = None,
) -> FastAPI:
    from dotenv import load_dotenv

    # .env supplies OPAL_LOOK_* env vars (token, data dir, credentials);
    # never overrides variables already present in the environment.
    load_dotenv()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        for rt in getattr(app.state, "stream_runtimes", {}).values():
            rt.stop()
        app.state.store.close()

    app = FastAPI(
        title="OPAL Look",
        version=constants.SERVICE_VERSION,
        # The published OpenAPI contract is authoritative; do not serve a
        # generated spec that could drift from it.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    import time as _time
    app.state.started_monotonic = _time.monotonic()
    app.state.store = store if store is not None else Store(Path(data_dir) if data_dir else default_data_dir())
    # Bearer token is provisioned out of band; absence = loopback dev mode.
    token = auth_token if auth_token is not None else env_token()
    if token is not None and not token.strip():
        raise ValueError("auth_token must be non-empty")
    app.state.auth_token = token.strip() if token else None
    import threading as _th
    app.state.viewer_lock = _th.Lock()
    app.state.viewer_counts = {}
    app.state.frame_cache = FrameCache()
    app.state.stream_runtimes = {}
    from .store import sweep_expired
    app.state.swept = sweep_expired(app.state.store)
    load_plugin_adapters()
    load_capture_plugins()
    ensure_engines(app.state.store)

    # Outermost first: access log -> correlation -> bearer gate -> routes.
    app.add_middleware(BearerAuthMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(AccessLogMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(settings.router)
    app.include_router(engines.router)
    app.include_router(hardware.router)
    app.include_router(models.router)
    app.include_router(predict.router)
    app.include_router(streams.router)
    app.include_router(profiles.router)
    app.include_router(backup.router)
    app.include_router(service.router)

    from fastapi.staticfiles import StaticFiles
    app.mount("/app", StaticFiles(directory=Path(__file__).parent / "static", html=True),
              name="app")
    return app

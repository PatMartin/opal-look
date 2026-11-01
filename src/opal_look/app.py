"""Application factory."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from . import constants
from .access_log import AccessLogMiddleware
from .correlation import CorrelationMiddleware
from .engines import ensure_default_model, ensure_engines, load_plugin_adapters
from .errors import register_error_handlers
from .framecache import FrameCache
from .sessions import SessionRuntimeRegistry
from .routers import (
    analyze, backup, engines, health, media, models, profiles, results,
    sessions as sessions_router, settings, snapshots, sources,
)
from .store import Store


def default_data_dir() -> Path:
    return Path(os.environ.get("OPAL_LOOK_DATA_DIR", "data"))


def create_app(data_dir: Path | str | None = None, store: Store | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
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
    app.state.store = store if store is not None else Store(Path(data_dir) if data_dir else default_data_dir())
    # Event transport is provisioned out of band; absence blocks events_enabled=true.
    app.state.event_transport = os.environ.get("OPAL_LOOK_EVENT_TRANSPORT") or None
    app.state.frame_cache = FrameCache()
    app.state.session_runtimes = SessionRuntimeRegistry()
    app.state.store.sessions.fail_interrupted(
        '{"code":"service_restarted","message":"service restarted before completion"}')
    load_plugin_adapters()
    ensure_engines(app.state.store)
    ensure_default_model(app.state.store)

    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(AccessLogMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(settings.router)
    app.include_router(engines.router)
    app.include_router(models.router)
    app.include_router(sources.router)
    app.include_router(profiles.router)
    app.include_router(media.router)
    app.include_router(analyze.router)
    app.include_router(results.router)
    app.include_router(snapshots.router)
    app.include_router(sessions_router.router)
    app.include_router(backup.router)

    from fastapi.staticfiles import StaticFiles
    app.mount("/app", StaticFiles(directory=Path(__file__).parent / "static", html=True),
              name="app")
    return app

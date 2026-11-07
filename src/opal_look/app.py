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
from .engines import ensure_default_model, ensure_engines, load_plugin_adapters
from .errors import register_error_handlers
from .framecache import FrameCache
from .sessions import SessionRuntimeRegistry
from .routers import (
    analyze, capabilities, configuration, engines, health, media, jobs, metrics, models, monitors, observations, pipelines, profiles, recordings, settings, sources,
)
from .store import Store


def default_data_dir() -> Path:
    return Path(os.environ.get("OPAL_LOOK_DATA_DIR", "data"))


def create_app(
    data_dir: Path | str | None = None,
    store: Store | None = None,
    auth_token: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        jr = getattr(app.state, "job_runtime", None)
        if jr is not None:
            jr.stop_all()
        for rt in getattr(app.state, "recording_runtimes", {}).values():
            rt.stop()
        for rt in getattr(app.state, "monitor_runtimes", {}).values():
            rt.stop()
        jr = getattr(app.state, "job_runtime", None)
        if jr is not None:
            jr.stop_all()
        for rt in getattr(app.state, "monitor_runtimes", {}).values():
            if rt._thread is not None:
                rt._thread.join(timeout=2.0)
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
    # Event transport is provisioned out of band; absence blocks events_enabled=true.
    app.state.event_transport = os.environ.get("OPAL_LOOK_EVENT_TRANSPORT") or None
    # Bearer token is provisioned out of band; absence = loopback dev mode.
    token = auth_token if auth_token is not None else env_token()
    if token is not None and not token.strip():
        raise ValueError("auth_token must be non-empty")
    app.state.auth_token = token.strip() if token else None
    from .jobs import JobRuntime
    app.state.job_runtime = JobRuntime(app.state.store, app)
    app.state.recording_runtimes = {}
    app.state.monitor_runtimes = {}
    app.state.viewer_counts = {}
    import threading as _th
    app.state.viewer_lock = _th.Lock()
    app.state.frame_cache = FrameCache()
    app.state.session_runtimes = SessionRuntimeRegistry()
    app.state.store.sessions.fail_interrupted(
        '{"code":"service_restarted","message":"service restarted before completion"}')
    from .store import sweep_expired
    app.state.swept = sweep_expired(app.state.store)
    from .monitors import recover_monitors
    app.state.recovered_monitors = recover_monitors(
        app.state.store, app.state.monitor_runtimes, app)
    from .jobs import recover_jobs
    app.state.recovered_jobs = recover_jobs(app.state.store, app)
    from .recordings import recover_recordings
    recover_recordings(app.state.store, app.state.recording_runtimes)
    load_plugin_adapters()
    load_capture_plugins()
    ensure_engines(app.state.store)
    ensure_default_model(app.state.store)

    # Outermost first: access log -> correlation -> bearer gate -> routes.
    app.add_middleware(BearerAuthMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(AccessLogMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(capabilities.router)
    app.include_router(settings.router)
    app.include_router(engines.router)
    app.include_router(models.router)
    app.include_router(sources.router)
    app.include_router(pipelines.router)
    app.include_router(profiles.router)
    app.include_router(observations.router)
    app.include_router(jobs.router)
    app.include_router(monitors.router)
    app.include_router(recordings.router)
    app.include_router(configuration.router)
    app.include_router(metrics.router)
    app.include_router(media.router)
    app.include_router(analyze.router)

    from fastapi.staticfiles import StaticFiles
    app.mount("/app", StaticFiles(directory=Path(__file__).parent / "static", html=True),
              name="app")
    return app

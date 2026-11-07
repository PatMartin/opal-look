"""Health, liveness, readiness and service-info endpoints (kernel shapes)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..constants import (
    API_VERSION,
    CONTRACT_VERSION,
    DEFAULT_MAX_IMAGE_PIXELS,
    DEFAULT_MAX_UPLOAD_BYTES,
    IMAGE_CONTENT_TYPES,
    SERVICE_DESCRIPTION,
    SERVICE_NAME,
    SERVICE_VERSION,
)
from ..engines import engine_runtime
from ..settings import effective_settings
from ..timeutil import now_iso

router = APIRouter()


def _readiness(store) -> tuple[bool, str]:
    """Ready: storage usable and at least one enabled model on an
    available engine can serve an analysis task."""
    if not store.ping():
        return False, "unavailable"
    for model in store.models.list(enabled=True):
        if _model_available(store, model):
            return True, "ok"
    return False, "unavailable"


def _model_available(store, model_row) -> bool:
    engine_row = store.engines.get(model_row["engine_id"])
    if engine_row is None:
        return False
    read = engine_runtime(store, engine_row)
    return read["enabled"] and read["available"]


def _health_read(request: Request, store) -> dict:
    """Kernel OpalHealthReport: aggregate status plus suite-standard sections."""
    storage_ok = store.ping()
    ready, status = _readiness(store)
    engines = [engine_runtime(store, row) for row in store.engines.list()]
    if ready and any(e["enabled"] and not e["available"] for e in engines):
        status = "degraded"

    app = request.app
    app_settings = effective_settings(store)
    events_enabled = bool(getattr(app_settings, "events_enabled", False))
    transport = getattr(app.state, "event_transport", None)
    publisher = getattr(app.state, "event_publisher", None)
    stats = (publisher.stats() if publisher else
             {"published": 0, "dropped": 0, "rate_limited": 0})
    started = getattr(app.state, "started_monotonic", None)
    uptime = (time.monotonic() - started) if started is not None else 0.0
    models_available = sum(
        1 for m in store.models.list(enabled=True) if _model_available(store, m))
    monitors_running = sum(
        1 for rt in getattr(app.state, "monitor_runtimes", {}).values() if rt.alive)
    sessions_active = (store.sessions.count_nonterminal()
                       if hasattr(store.sessions, "count_nonterminal") else 0)
    jobs_nonterminal = (store.jobs.count_nonterminal()
                        if hasattr(store.jobs, "count_nonterminal") else 0)
    recordings_active = (store.recordings.count_active()
                         if hasattr(store.recordings, "count_active") else 0)
    obs_total = (store.observations.count()
                 if hasattr(store.observations, "count") else 0)
    engine_state = ("ok" if all(not e["enabled"] or e["available"] for e in engines)
                    else "degraded")
    return {
        "status": status,
        "version": SERVICE_VERSION,
        "ready": ready,
        "active_profile_id": None,
        "engines": [
            {
                "engine_id": e["engine_id"],
                "name": e["name"],
                "enabled": e["enabled"],
                "available": e["available"],
                "state": ("disabled" if not e["enabled"]
                          else "ready" if e["available"] else "unavailable"),
                "message": e["message"],
            }
            for e in engines
        ],
        "details": {
            "storage": "ok" if storage_ok else "unavailable",
            "media_capabilities": {
                "image_content_types": IMAGE_CONTENT_TYPES,
                "video_content_types": [],
                "video_codecs": [],
                "max_upload_bytes": DEFAULT_MAX_UPLOAD_BYTES,
                "max_image_pixels": DEFAULT_MAX_IMAGE_PIXELS,
            },
            "event_publication": {
                "enabled": events_enabled,
                "status": ("provisioned" if events_enabled and transport
                           else "unprovisioned" if events_enabled else "disabled"),
                "published": stats.get("published", 0),
                "dropped": stats.get("dropped", 0),
                "rate_limited": stats.get("rate_limited", 0),
                "queue_depth": stats.get("queue_depth", 0),
                "message": None,
            },
        },
        "broker_running": bool(events_enabled and transport),
        "database_ready": storage_ok,
        "pending_restart": False,
        "pending_restart_fields": [],
        "checks": [
            {"name": "database", "state": "ok" if storage_ok else "error"},
            {"name": "engines", "state": engine_state},
            {"name": "event_bus",
             "state": ("running" if events_enabled and transport
                       else "disabled" if not events_enabled else "unprovisioned")},
        ],
        "checked_at": now_iso(),
        "uptime_seconds": max(0.0, uptime),
        "components": {
            "database": {"state": "ok" if storage_ok else "error",
                         "detail": "sqlite"},
            "engines": {"state": engine_state},
            "event_bus": {
                "state": ("running" if events_enabled and transport
                          else "disabled" if not events_enabled else "unprovisioned"),
            },
        },
        "metrics": {
            "observations_persisted": obs_total,
            "events_published": stats.get("published", 0),
            "events_dropped": stats.get("dropped", 0),
            "sessions_active": sessions_active,
            "monitors_running": monitors_running,
            "jobs_nonterminal": jobs_nonterminal,
            "recordings_active": recordings_active,
        },
        "models_available": models_available,
        "event": ("not_configured" if not events_enabled
                  else "available" if transport else "unavailable"),
        "active_tasks": sessions_active + monitors_running + jobs_nonterminal
        + recordings_active,
    }


@router.get("/api/v1/health/")
def get_api_v1_health(request: Request, store: StoreDep) -> dict:
    return _health_read(request, store)


@router.get("/api/v1/health/live")
def get_api_v1_health_live() -> dict:
    """Kernel OpalHealthProbe: process is alive."""
    return {"status": "ok", "ready": True, "details": {},
            "version": SERVICE_VERSION}


@router.get("/api/v1/health/ready")
def get_api_v1_health_ready(store: StoreDep) -> JSONResponse:
    """Kernel OpalHealthProbe: can the service do useful work."""
    ready, status = _readiness(store)
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": status, "ready": ready, "details": {},
                 "version": SERVICE_VERSION},
    )


@router.get("/health")
def get_health_alias() -> dict:
    return {"status": "ok"}


@router.get("/")
def get_service_info() -> dict:
    return {
        "name": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "api_version": API_VERSION,
        "contract_version": CONTRACT_VERSION,
        "description": SERVICE_DESCRIPTION,
    }

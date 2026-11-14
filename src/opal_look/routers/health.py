"""Health, liveness, readiness and service-info endpoints (kernel shapes)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..constants import (
    API_VERSION,
    CONTRACT_VERSION,
    SERVICE_DESCRIPTION,
    SERVICE_NAME,
    SERVICE_VERSION,
)
from ..engines import engine_runtime
from ..timeutil import now_iso

router = APIRouter()


def _readiness(store) -> tuple[bool, str]:
    """Ready: storage usable. Engines are optional — video-only streams
    work with zero AI engines installed."""
    if not store.ping():
        return False, "unavailable"
    return True, "ok"


def _health_read(request: Request, store) -> dict:
    """Kernel OpalHealthReport: aggregate status plus suite-standard sections."""
    storage_ok = store.ping()
    ready, status = _readiness(store)
    engines = [engine_runtime(store, row) for row in store.engines.list()]
    if ready and any(e["enabled"] and not e["available"] for e in engines):
        status = "degraded"

    app = request.app
    started = getattr(app.state, "started_monotonic", None)
    uptime = (time.monotonic() - started) if started is not None else 0.0
    engine_state = ("ok" if all(not e["enabled"] or e["available"] for e in engines)
                    else "degraded")
    return {
        "status": status,
        "version": SERVICE_VERSION,
        "ready": ready,
        "active_profile_id": (
            store.profiles.get_active()["profile_id"]
            if store.profiles.get_active() is not None else None),
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
        },
        "database_ready": storage_ok,
        "pending_restart": False,
        "pending_restart_fields": [],
        "checks": [
            {"name": "database", "state": "ok" if storage_ok else "error"},
            {"name": "engines", "state": engine_state},
        ],
        "checked_at": now_iso(),
        "uptime_seconds": max(0.0, uptime),
        "components": {
            "database": {"state": "ok" if storage_ok else "error",
                         "detail": "sqlite"},
            "engines": {"state": engine_state},
        },
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


@router.get("/api/v1/info/")
def get_info() -> dict:
    """Kernel ServiceInfo on the contract path; same payload as GET /."""
    return get_service_info()


@router.get("/api/v1/info/ping")
def get_info_ping() -> dict:
    """Kernel LivenessRead for process supervisors."""
    return {"status": "ok"}

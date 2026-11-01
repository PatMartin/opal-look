"""Health, liveness, readiness and service-info endpoints."""

from __future__ import annotations

from fastapi import APIRouter
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
from ..engines import engine_read

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
    read = engine_read(store, engine_row)
    return read["enabled"] and read["available"]


def _health_read(store) -> dict:
    storage_ok = store.ping()
    ready, status = _readiness(store)
    engines = [engine_read(store, row) for row in store.engines.list()]
    if ready and any(e["enabled"] and not e["available"] for e in engines):
        status = "degraded"
    return {
        "status": status,
        "ready": ready,
        "engines": [
            {
                "engine_id": e["engine_id"],
                "enabled": e["enabled"],
                "available": e["available"],
                "message": e["message"],
            }
            for e in engines
        ],
        "active_sessions": 0,
        "details": {"storage": "ok" if storage_ok else "unavailable"},
        "media_capabilities": {
            "image_content_types": IMAGE_CONTENT_TYPES,
            "video_content_types": [],
            "video_codecs": [],
            "max_upload_bytes": DEFAULT_MAX_UPLOAD_BYTES,
            "max_image_pixels": DEFAULT_MAX_IMAGE_PIXELS,
        },
        "event_publication": {
            "enabled": False,
            "status": "disabled",
            "published": 0,
            "dropped": 0,
            "rate_limited": 0,
            "queue_depth": 0,
            "message": None,
        },
    }


@router.get("/api/v1/health/")
def get_api_v1_health(store: StoreDep) -> dict:
    return _health_read(store)


@router.get("/api/v1/health/live")
def get_api_v1_health_live() -> dict:
    return {"status": "ok", "ready": True, "details": {}}


@router.get("/api/v1/health/ready")
def get_api_v1_health_ready(store: StoreDep) -> JSONResponse:
    ready, status = _readiness(store)
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": status, "ready": ready, "details": {}},
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

"""Health, liveness, readiness and service-info endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

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

router = APIRouter()


def _readiness(request: Request) -> tuple[bool, str]:
    """(ready, status). Ready requires usable storage plus at least one
    enabled model on an available engine; none are registered yet."""
    store = request.app.state.store
    if not store.ping():
        return False, "unavailable"
    # No engines/models registered yet -> cannot serve analysis.
    return False, "unavailable"


def _health_read(request: Request) -> dict:
    store = request.app.state.store
    storage_ok = store.ping()
    ready, status = _readiness(request)
    return {
        "status": status,
        "ready": ready,
        "engines": [],
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
def get_api_v1_health(request: Request) -> dict:
    return _health_read(request)


@router.get("/api/v1/health/live")
def get_api_v1_health_live() -> dict:
    return {"status": "ok", "ready": True, "details": {}}


@router.get("/api/v1/health/ready")
def get_api_v1_health_ready(request: Request) -> JSONResponse:
    ready, status = _readiness(request)
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

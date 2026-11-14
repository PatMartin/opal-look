"""Engine-local hardware endpoints (adapter-reported compute devices)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..engines import ENGINE_REGISTRY
from ..errors import ApiError

router = APIRouter()


def _devices(engine_id: str | None) -> list[dict]:
    adapters = (
        [ENGINE_REGISTRY.get(engine_id)]
        if engine_id is not None
        else ENGINE_REGISTRY.all()
    )
    out: list[dict] = []
    for adapter in adapters:
        if adapter is None:
            continue
        for dev in adapter.hardware():
            out.append({"engine_id": adapter.engine_id, **dev})
    return out


@router.get("/api/v1/hardware/")
def get_api_v1_hardware(request: Request,
                        engine_id: str | None = None) -> JSONResponse:
    return JSONResponse(_devices(engine_id))


@router.get("/api/v1/hardware/{device_id}")
def get_api_v1_hardware_device(request: Request, device_id: str,
                               engine_id: str | None = None) -> JSONResponse:
    matches = [d for d in _devices(engine_id) if d["device_id"] == device_id]
    if not matches:
        raise ApiError(404, f"Unknown device: {device_id!r}")
    return JSONResponse(matches[0])

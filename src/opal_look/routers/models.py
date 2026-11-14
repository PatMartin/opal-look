"""Model endpoints: engine-federated catalog, load/unload lifecycle."""

from __future__ import annotations


from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..engines import (ENGINE_REGISTRY, EngineUnavailable, ModelNotFound,
                       engine_gate)
from ..errors import ApiError

router = APIRouter()


def _catalog(engine_id: str | None) -> list[dict]:
    adapters = (
        [ENGINE_REGISTRY.get(engine_id)]
        if engine_id is not None
        else ENGINE_REGISTRY.all()
    )
    out: list[dict] = []
    for adapter in adapters:
        if adapter is None:
            continue
        out.extend(adapter.models())
    return out


def _resolve_owner(model_id: str, engine_id: str | None):
    owners = [a for a in
              ([ENGINE_REGISTRY.get(engine_id)] if engine_id
               else ENGINE_REGISTRY.all())
              if a is not None
              and any(m["model_id"] == model_id for m in a.models())]
    if not owners:
        raise ApiError(404, f"Unknown model: {model_id!r}")
    if len(owners) > 1:
        raise ApiError(422, f"Model {model_id!r} is owned by multiple engines; "
                            "supply engine_id.")
    return owners[0]


@router.get("/api/v1/model/")
def get_api_v1_models(request: Request,
                    engine_id: str | None = None) -> JSONResponse:
    return JSONResponse(_catalog(engine_id))


@router.get("/api/v1/model/{model_id}")
def get_api_v1_model(request: Request, model_id: str,
                   engine_id: str | None = None) -> JSONResponse:
    adapter = _resolve_owner(model_id, engine_id)
    model = next(m for m in adapter.models() if m["model_id"] == model_id)
    return JSONResponse(model)


@router.post("/api/v1/model/{model_id}/load")
def post_api_v1_model_load(request: Request, store: StoreDep, model_id: str,
                           engine_id: str | None = None) -> JSONResponse:
    adapter = _resolve_owner(model_id, engine_id)
    engine_gate(store, adapter)
    try:
        return JSONResponse(adapter.load_model(model_id, device_id=None))
    except ModelNotFound:
        raise ApiError(404, f"Unknown model: {model_id!r}")
    except EngineUnavailable as exc:
        raise ApiError(503, str(exc))


@router.post("/api/v1/model/{model_id}/unload")
def post_api_v1_model_unload(request: Request, store: StoreDep, model_id: str,
                             engine_id: str | None = None) -> JSONResponse:
    adapter = _resolve_owner(model_id, engine_id)
    runtimes = getattr(request.app.state, "stream_runtimes", {})
    active = [sid for sid, rt in runtimes.items()
              if getattr(rt, "model_id", None) == model_id
              and getattr(rt, "status", None) in ("starting", "running")]
    if active:
        raise ApiError(409, f"Model {model_id!r} is in use by "
                            f"{len(active)} active stream(s).")
    try:
        return JSONResponse(adapter.unload_model(model_id))
    except ModelNotFound:
        raise ApiError(404, f"Unknown model: {model_id!r}")
    except EngineUnavailable as exc:
        raise ApiError(503, str(exc))

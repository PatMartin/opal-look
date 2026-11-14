"""Engine endpoints: list, show, patch, discover, capabilities."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..engines import (ENGINE_REGISTRY, engine_read, ensure_engines,
                       load_plugin_adapters)
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..schemas import EnginePatch, reject_null_fields
from ..store import Store

router = APIRouter()


def _get_engine_or_404(store: Store, engine_id: str):
    row = store.engines.get(engine_id)
    if row is None or engine_id not in ENGINE_REGISTRY:
        raise ApiError(404, f"Unknown engine: {engine_id!r}")
    return row


@router.get("/api/v1/engine/")
def get_api_v1_engines(request: Request, store: StoreDep) -> JSONResponse:
    body = [
        engine_read(store, row)
        for row in store.engines.list()
        if row["engine_id"] in ENGINE_REGISTRY
    ]
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.get("/api/v1/engine/{engine_id}")
def get_api_v1_engines_engine_id(
    request: Request, store: StoreDep, engine_id: str
) -> JSONResponse:
    row = _get_engine_or_404(store, engine_id)
    return JSONResponse(engine_read(store, row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/engine/{engine_id}")
def patch_api_v1_engines_engine_id(
    request: Request, store: StoreDep, engine_id: str, patch: EnginePatch
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    reject_null_fields(supplied)

    require_if_match(request)
    _get_engine_or_404(store, engine_id)
    adapter = ENGINE_REGISTRY.get(engine_id)

    if "options" in supplied:
        errors = adapter.validate_config(supplied["options"])
        if errors:
            raise ApiError(422, "Invalid engine options.", details=errors)
    fields = dict(supplied)
    if "options" in fields:
        fields["config"] = fields.pop("options")
    with store.write_txn():
        check_if_match(request, store)
        if fields:
            store.engines.update(engine_id, fields)
        revision = store.bump_revision()
    row = store.engines.get(engine_id)
    return JSONResponse(engine_read(store, row), headers={"ETag": revision})


@router.post("/api/v1/engine/discover")
def post_api_v1_engine_discover(request: Request, store: StoreDep) -> JSONResponse:
    """Re-scan adapter entry points and report the usable catalog.

    An empty engines array is healthy: video-only streams need no engine.
    Plugin load failures surface in errors without failing the scan."""
    load_plugin_adapters()
    ensure_engines(store)
    engines = [
        engine_read(store, row)
        for row in store.engines.list()
        if row["engine_id"] in ENGINE_REGISTRY
    ]
    return JSONResponse({"engines": engines, "errors": list(ENGINE_REGISTRY.errors)})


@router.get("/api/v1/engine/{engine_id}/capabilities")
def get_api_v1_engine_capabilities(
    request: Request, store: StoreDep, engine_id: str
) -> JSONResponse:
    _get_engine_or_404(store, engine_id)
    adapter = ENGINE_REGISTRY.get(engine_id)
    return JSONResponse({"engine_id": engine_id, **adapter.capabilities()})

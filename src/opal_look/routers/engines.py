"""Engine endpoints: discovery, read, update, validate."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..engines import ADAPTERS, engine_read
from ..errors import ApiError
from ..precondition import check_if_match
from ..refs import nonterminal_sessions_referencing
from ..schemas import EngineUpdate, reject_null_fields

router = APIRouter()


def _get_engine_or_404(request: Request, engine_id: str):
    store = request.app.state.store
    row = store.get_engine(engine_id)
    if row is None or engine_id not in ADAPTERS:
        raise ApiError(404, f"Unknown engine: {engine_id!r}")
    return row


@router.get("/api/v1/engines/")
def get_api_v1_engines(request: Request) -> JSONResponse:
    store = request.app.state.store
    body = [engine_read(store, row) for row in store.list_engines() if row["engine_id"] in ADAPTERS]
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.get("/api/v1/engines/{engine_id}")
def get_api_v1_engines_engine_id(request: Request, engine_id: str) -> JSONResponse:
    store = request.app.state.store
    row = _get_engine_or_404(request, engine_id)
    return JSONResponse(engine_read(store, row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/engines/{engine_id}")
def patch_api_v1_engines_engine_id(
    request: Request, engine_id: str, patch: EngineUpdate
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    reject_null_fields(supplied)

    store = request.app.state.store
    row = _get_engine_or_404(request, engine_id)
    adapter = ADAPTERS[engine_id]

    if "config" in supplied:
        errors = adapter.validate_config(supplied["config"])
        if errors:
            raise ApiError(422, "Invalid engine configuration.", details=errors)
    if nonterminal_sessions_referencing(store, "engine", engine_id):
        raise ApiError(409, f"Engine {engine_id!r} is referenced by a nonterminal session.")

    with store.write_txn():
        check_if_match(request, store)
        if supplied:
            store.update_engine(engine_id, supplied)
        revision = store.bump_revision()
    row = store.get_engine(engine_id)
    return JSONResponse(engine_read(store, row), headers={"ETag": revision})


@router.post("/api/v1/engines/{engine_id}/validate")
def post_api_v1_engines_engine_id_validate(request: Request, engine_id: str) -> dict:
    store = request.app.state.store
    _get_engine_or_404(request, engine_id)
    adapter = ADAPTERS[engine_id]
    read = engine_read(store, store.get_engine(engine_id))

    errors = adapter.validate_config(read["config"])
    if not read["enabled"]:
        errors.append("engine is disabled")
    if not read["available"]:
        errors.append(f"engine unavailable: {read['message'] or 'probe failed'}")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": [],
        "details": {"engine_id": engine_id, "adapter": adapter.metadata()},
    }

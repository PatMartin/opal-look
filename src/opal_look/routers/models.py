"""Model registration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from ..engines import ADAPTERS, model_read
from ..errors import ApiError
from ..precondition import check_if_match
from ..refs import (
    media_dependencies,
    nonterminal_sessions_referencing,
    profiles_referencing_model,
)
from ..schemas import (
    IDENTIFIER_PATTERN,
    ModelCreate,
    ModelUpdate,
    Task,
    reject_null_fields,
)

router = APIRouter()


def _get_model_or_404(request: Request, model_id: str):
    row = request.app.state.store.get_model(model_id)
    if row is None:
        raise ApiError(404, f"Unknown model: {model_id!r}")
    return row


def _engine_or_404(request: Request, engine_id: str):
    row = request.app.state.store.get_engine(engine_id)
    if row is None or engine_id not in ADAPTERS:
        raise ApiError(404, f"Unknown engine: {engine_id!r}")
    return row


def _model_references(request: Request, model_id: str) -> None:
    store = request.app.state.store
    if (
        nonterminal_sessions_referencing(store, "model", model_id)
        or profiles_referencing_model(store, model_id)
        or media_dependencies(store, model_id)
    ):
        raise ApiError(409, f"Model {model_id!r} is referenced by other resources.")


@router.get("/api/v1/models/")
def get_api_v1_models(
    request: Request,
    engine_id: str | None = Query(default=None, pattern=IDENTIFIER_PATTERN),
    task: Task | None = Query(default=None),
    enabled: bool | None = Query(default=None),
) -> JSONResponse:
    store = request.app.state.store
    rows = store.list_models(engine_id=engine_id, enabled=enabled)
    body = [model_read(store, row) for row in rows]
    if task is not None:
        body = [model for model in body if task in model["tasks"]]
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.post("/api/v1/models/", status_code=201)
def post_api_v1_models(request: Request, model: ModelCreate) -> JSONResponse:
    store = request.app.state.store
    if store.get_model(model.model_id) is not None:
        raise ApiError(409, f"Model {model.model_id!r} already exists.")
    _engine_or_404(request, model.engine_id)

    adapter = ADAPTERS[model.engine_id]
    errors, _ = adapter.validate_model(model.resource)
    if errors:
        raise ApiError(422, "Invalid model resource locator.", details=errors)

    with store.write_txn():
        check_if_match(request, store)
        store.insert_model(model.model_id, model.name, model.engine_id, model.resource, model.enabled)
        revision = store.bump_revision()
    row = store.get_model(model.model_id)
    return JSONResponse(
        model_read(store, row),
        status_code=201,
        headers={"ETag": revision, "Location": f"/api/v1/models/{model.model_id}"},
    )


@router.get("/api/v1/models/{model_id}")
def get_api_v1_models_model_id(request: Request, model_id: str) -> JSONResponse:
    store = request.app.state.store
    row = _get_model_or_404(request, model_id)
    return JSONResponse(model_read(store, row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/models/{model_id}")
def patch_api_v1_models_model_id(
    request: Request, model_id: str, patch: ModelUpdate
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    reject_null_fields(supplied)

    store = request.app.state.store
    _get_model_or_404(request, model_id)
    if "engine_id" in supplied:
        _engine_or_404(request, supplied["engine_id"])
    if "resource" in supplied:
        adapter = ADAPTERS[supplied.get("engine_id") or store.get_model(model_id)["engine_id"]]
        errors, _ = adapter.validate_model(supplied["resource"])
        if errors:
            raise ApiError(422, "Invalid model resource locator.", details=errors)
    _model_references(request, model_id)

    with store.write_txn():
        check_if_match(request, store)
        if supplied:
            store.update_model(model_id, supplied)
        revision = store.bump_revision()
    row = store.get_model(model_id)
    return JSONResponse(model_read(store, row), headers={"ETag": revision})


@router.delete("/api/v1/models/{model_id}", status_code=204)
def delete_api_v1_models_model_id(request: Request, response: Response, model_id: str) -> None:
    store = request.app.state.store
    _get_model_or_404(request, model_id)
    _model_references(request, model_id)
    with store.write_txn():
        check_if_match(request, store)
        store.delete_model(model_id)
        response.headers["ETag"] = store.bump_revision()


@router.post("/api/v1/models/{model_id}/validate")
def post_api_v1_models_model_id_validate(request: Request, model_id: str) -> dict:
    store = request.app.state.store
    row = _get_model_or_404(request, model_id)
    read = model_read(store, row)
    adapter = ADAPTERS[read["engine_id"]]

    errors, warnings = adapter.validate_model(read["resource"])
    if read["engine_id"] not in ADAPTERS or store.get_engine(read["engine_id"]) is None:
        errors.append(f"engine {read['engine_id']!r} is not installed")
    elif not read["enabled"]:
        errors.append("model is disabled")
    elif not read["available"]:
        errors.append("model is not currently available")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "details": {"engine_id": read["engine_id"], "tasks": read["tasks"]},
    }

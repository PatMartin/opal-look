"""Model registration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..engines import ENGINE_REGISTRY, model_read
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
from ..store import Store

router = APIRouter()


def _get_model_or_404(store: Store, model_id: str):
    row = store.models.get(model_id)
    if row is None:
        raise ApiError(404, f"Unknown model: {model_id!r}")
    return row


def _engine_or_404(store: Store, engine_id: str):
    row = store.engines.get(engine_id)
    if row is None or engine_id not in ENGINE_REGISTRY:
        raise ApiError(404, f"Unknown engine: {engine_id!r}")
    return row


def _session_refs(store: Store, model_id: str) -> None:
    if nonterminal_sessions_referencing(store, "model", model_id):
        raise ApiError(409, f"Model {model_id!r} is referenced by a nonterminal session.")


def _delete_refs(store: Store, model_id: str) -> None:
    if (
        nonterminal_sessions_referencing(store, "model", model_id)
        or profiles_referencing_model(store, model_id)
        or media_dependencies(store, model_id)
    ):
        raise ApiError(409, f"Model {model_id!r} is referenced by other resources.")


@router.get("/api/v1/models/")
def get_api_v1_models(
    request: Request,
    store: StoreDep,
    engine_id: str | None = Query(default=None, pattern=IDENTIFIER_PATTERN),
    task: Task | None = Query(default=None),
    enabled: bool | None = Query(default=None),
) -> JSONResponse:
    rows = store.models.list(engine_id=engine_id, enabled=enabled)
    body = [model_read(store, row) for row in rows]
    if task is not None:
        body = [model for model in body if task in model["tasks"]]
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.post("/api/v1/models/", status_code=201)
def post_api_v1_models(request: Request, store: StoreDep, model: ModelCreate) -> JSONResponse:
    if store.models.get(model.model_id) is not None:
        raise ApiError(409, f"Model {model.model_id!r} already exists.")
    _engine_or_404(store, model.engine_id)

    adapter = ENGINE_REGISTRY.get(model.engine_id)
    errors, _ = adapter.validate_model(model.resource)
    if errors:
        raise ApiError(422, "Invalid model resource locator.", details=errors)

    with store.write_txn():
        check_if_match(request, store)
        store.models.insert(model.model_id, model.name, model.engine_id, model.resource, model.enabled)
        revision = store.bump_revision()
    row = store.models.get(model.model_id)
    return JSONResponse(
        model_read(store, row),
        status_code=201,
        headers={"ETag": revision, "Location": f"/api/v1/models/{model.model_id}"},
    )


@router.get("/api/v1/models/{model_id}")
def get_api_v1_models_model_id(request: Request, store: StoreDep, model_id: str) -> JSONResponse:
    row = _get_model_or_404(store, model_id)
    return JSONResponse(model_read(store, row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/models/{model_id}")
def patch_api_v1_models_model_id(
    request: Request, store: StoreDep, model_id: str, patch: ModelUpdate
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    reject_null_fields(supplied)

    check_if_match(request, store)
    _get_model_or_404(store, model_id)
    if "engine_id" in supplied:
        _engine_or_404(store, supplied["engine_id"])
    if "resource" in supplied:
        adapter = ENGINE_REGISTRY.get(supplied.get("engine_id") or store.models.get(model_id)["engine_id"])
        errors, _ = adapter.validate_model(supplied["resource"])
        if errors:
            raise ApiError(422, "Invalid model resource locator.", details=errors)
    _session_refs(store, model_id)

    with store.write_txn():
        check_if_match(request, store)
        if supplied:
            store.models.update(model_id, supplied)
        revision = store.bump_revision()
    row = store.models.get(model_id)
    return JSONResponse(model_read(store, row), headers={"ETag": revision})


@router.delete("/api/v1/models/{model_id}", status_code=204)
def delete_api_v1_models_model_id(
    request: Request, response: Response, store: StoreDep, model_id: str
) -> None:
    check_if_match(request, store)
    _get_model_or_404(store, model_id)
    _delete_refs(store, model_id)
    with store.write_txn():
        check_if_match(request, store)
        store.models.delete(model_id)
        response.headers["ETag"] = store.bump_revision()


@router.post("/api/v1/models/{model_id}/validate")
def post_api_v1_models_model_id_validate(request: Request, store: StoreDep, model_id: str) -> dict:
    row = _get_model_or_404(store, model_id)
    read = model_read(store, row)
    adapter = ENGINE_REGISTRY.get(read["engine_id"])

    errors, warnings = adapter.validate_model(read["resource"])
    if store.engines.get(read["engine_id"]) is None:
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

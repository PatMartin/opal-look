"""Model registration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..engines import ENGINE_REGISTRY, model_read, model_runtime
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..refs import (
    media_dependencies,
    nonterminal_sessions_referencing,
    profiles_referencing_model,
)
from ..schemas import (
    IDENTIFIER_PATTERN,
    ModelCreate,
    ModelPatch,
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


@router.get("/api/v1/model/")
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


@router.post("/api/v1/model/", status_code=201)
def post_api_v1_models(request: Request, store: StoreDep, model: ModelCreate) -> JSONResponse:
    if store.models.get(model.id) is not None:
        raise ApiError(409, f"Model {model.id!r} already exists.")
    _engine_or_404(store, model.engine_id)

    adapter = ENGINE_REGISTRY.get(model.engine_id)
    supported = set(adapter.capabilities().get("tasks", []))
    unsupported = [t for t in model.tasks if t not in supported]
    if unsupported:
        raise ApiError(
            422,
            f"Tasks unsupported by engine {model.engine_id!r}: {sorted(unsupported)}",
            details={"unsupported_tasks": sorted(unsupported),
                     "supported_tasks": sorted(supported)},
        )
    resource = {"ref": model.resource_ref}
    errors, _ = adapter.validate_model(resource)
    if errors:
        raise ApiError(422, "Invalid model resource reference.", details=errors)
    if model.options is not None:
        opt_errors = adapter.validate_engine_options(model.options)
        if opt_errors:
            raise ApiError(422, "Invalid model options.", details=opt_errors)

    with store.write_txn():
        check_if_match(request, store)
        store.models.insert(
            model.id, model.id, model.engine_id, resource, True,
            tasks=list(model.tasks), options=model.options or {},
            resource_ref=model.resource_ref,
        )
        revision = store.bump_revision()
    row = store.models.get(model.id)
    return JSONResponse(
        model_read(store, row),
        status_code=201,
        headers={"ETag": revision, "Location": f"/api/v1/model/{model.id}"},
    )


@router.get("/api/v1/model/{model_id}")
def get_api_v1_models_model_id(request: Request, store: StoreDep, model_id: str) -> JSONResponse:
    row = _get_model_or_404(store, model_id)
    return JSONResponse(model_read(store, row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/model/{model_id}")
def patch_api_v1_models_model_id(
    request: Request, store: StoreDep, model_id: str, patch: ModelPatch
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    reject_null_fields(supplied)

    require_if_match(request)
    row = _get_model_or_404(store, model_id)
    fields = {}
    if "display_name" in supplied:
        fields["name"] = supplied["display_name"]
    if "options" in supplied:
        adapter = ENGINE_REGISTRY.get(row["engine_id"])
        opt_errors = adapter.validate_engine_options(supplied["options"])
        if opt_errors:
            raise ApiError(422, "Invalid model options.", details=opt_errors)
        fields["options"] = supplied["options"]
    _session_refs(store, model_id)

    with store.write_txn():
        check_if_match(request, store)
        if fields:
            store.models.update(model_id, fields)
        revision = store.bump_revision()
    row = store.models.get(model_id)
    return JSONResponse(model_read(store, row), headers={"ETag": revision})


@router.delete("/api/v1/model/{model_id}", status_code=204)
def delete_api_v1_models_model_id(
    request: Request, response: Response, store: StoreDep, model_id: str
) -> None:
    require_if_match(request)
    _get_model_or_404(store, model_id)
    _delete_refs(store, model_id)
    with store.write_txn():
        check_if_match(request, store)
        store.models.delete(model_id)
        response.headers["ETag"] = store.bump_revision()


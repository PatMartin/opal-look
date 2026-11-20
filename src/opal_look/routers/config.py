"""Configuration snapshot endpoints (kernel config_save/load/validate).

Replaces the retired /api/v1/backup/* surface: save captures a portable
OpalConfigSnapshot (managed store or response body), load atomically
replaces persistent configuration under If-Match, validate runs the same
checks without mutating. No actions execute on load."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..configuration import (
    apply_snapshot, build_snapshot, load_managed, save_managed,
    validate_snapshot,
)
from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match

router = APIRouter()


def _registry(request: Request):
    return request.app.state.engine_registry


@router.post("/api/v1/config/save")
def post_api_v1_config_save(store: StoreDep, body: dict | None) -> JSONResponse:
    body = body or {}
    if not isinstance(body, dict):
        raise ApiError(422, "config save body must be a JSON object.")
    unknown = set(body) - {"destination"}
    if unknown:
        raise ApiError(422, f"Unknown fields: {sorted(unknown)}.")
    destination = body.get("destination", "managed")
    if destination not in ("managed", "response"):
        raise ApiError(422, "destination must be 'managed' or 'response'.")
    snapshot = build_snapshot(store)
    if destination == "managed":
        save_managed(store, snapshot)
    # Save is not a live mutation: ETag carries the captured revision.
    return JSONResponse(
        {"snapshot": snapshot, "managed": destination == "managed"},
        headers={"ETag": store.config_revision()})


@router.post("/api/v1/config/load")
def post_api_v1_config_load(request: Request, store: StoreDep,
                            body: dict | None) -> JSONResponse:
    require_if_match(request)
    body = body or {}
    if not isinstance(body, dict):
        raise ApiError(422, "config load body must be a JSON object.")
    unknown = set(body) - {"snapshot"}
    if unknown:
        raise ApiError(422, f"Unknown fields: {sorted(unknown)}.")
    if "snapshot" in body:
        if body["snapshot"] is None:
            raise ApiError(422, "An explicit null snapshot is invalid.")
        snapshot = body["snapshot"]
    else:
        snapshot = load_managed(store)
        if snapshot is None:
            raise ApiError(404, "No managed snapshot exists.")

    errors, warnings = validate_snapshot(store, snapshot, _registry(request))
    if errors:
        raise ApiError(422, "Snapshot is invalid: "
                            + "; ".join(e["message"] for e in errors[:4]),
                       details={"issues": errors})
    with store.write_txn():
        check_if_match(request, store)
        pending = apply_snapshot(store, snapshot, _registry(request))
        revision = store.bump_revision()
    return JSONResponse(
        {"applied": True, "pending_restart_fields": pending,
         "warnings": warnings},
        headers={"ETag": revision})


@router.post("/api/v1/config/validate")
def post_api_v1_config_validate(request: Request, store: StoreDep,
                                body: dict | None) -> JSONResponse:
    body = body or {}
    if not isinstance(body, dict):
        raise ApiError(422, "config validate body must be a JSON object.")
    unknown = set(body) - {"snapshot"}
    if unknown:
        raise ApiError(422, f"Unknown fields: {sorted(unknown)}.")
    if "snapshot" not in body:
        snapshot = build_snapshot(store)  # live configuration
    else:
        if body["snapshot"] is None:
            raise ApiError(422, "An explicit null snapshot is invalid.")
        snapshot = body["snapshot"]
    errors, warnings = validate_snapshot(store, snapshot, _registry(request))
    return JSONResponse({"valid": not errors,
                         "errors": errors, "warnings": warnings},
                        headers={"ETag": store.config_revision()})

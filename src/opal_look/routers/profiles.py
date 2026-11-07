"""Profile endpoints (kernel OpalProfile): list/create/show/patch/delete/activate."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..profiles import profile_read
from ..timeutil import now_iso

router = APIRouter()

# Fields that map to real columns; everything else persists in the data blob.
_PROFILE_CORE = {"id", "name", "is_active", "created_at", "updated_at"}


def _get_profile_or_404(store, profile_id: int):
    try:
        pid = int(profile_id)
    except (TypeError, ValueError):
        raise ApiError(404, f"Unknown profile: {profile_id}")
    row = store.profiles.get(pid)
    if row is None:
        raise ApiError(404, f"Unknown profile: {profile_id}")
    return row


def _validate_body(store, supplied: dict) -> None:
    if "name" in supplied and not supplied["name"]:
        raise ApiError(422, "Profile name must be non-empty.")
    pid = supplied.get("pipeline_id")
    if pid is not None and store.pipelines.get(pid) is None:
        raise ApiError(422, f"Unknown pipeline: {pid!r}")
    for key in ("inference", "retention", "confidence_thresholds",
                "engine_options", "model_paths"):
        if key in supplied and supplied[key] is not None \
                and not isinstance(supplied[key], dict):
            raise ApiError(422, f"{key} must be an object.")
    if "is_active" in supplied and not isinstance(supplied["is_active"], bool):
        raise ApiError(422, "is_active must be a boolean.")


@router.get("/api/v1/profiles/")
def get_api_v1_profiles(store: StoreDep) -> JSONResponse:
    return JSONResponse([profile_read(r) for r in store.profiles.list()],
                        headers={"ETag": store.config_revision()})


@router.post("/api/v1/profiles/", status_code=201)
def post_api_v1_profiles(request: Request, store: StoreDep, body: dict) -> JSONResponse:
    require_if_match(request)
    if not isinstance(body, dict):
        raise ApiError(422, "Profile body must be a JSON object.")
    if "name" not in body:
        raise ApiError(422, "Profile 'name' is required.")
    _validate_body(store, body)
    data = {k: v for k, v in body.items() if k not in _PROFILE_CORE}
    data["created_at"] = now_iso()
    data["updated_at"] = data["created_at"]
    with store.write_txn():
        check_if_match(request, store)
        pid = store.profiles.insert_kernel(
            {"name": body["name"], "is_active": bool(body.get("is_active")),
             "data": data})
        if body.get("is_active"):
            store.profiles.set_active(pid)
        revision = store.bump_revision()
    return JSONResponse(profile_read(store.profiles.get(pid)),
                        status_code=201, headers={"ETag": revision})


@router.get("/api/v1/profiles/{profile_id}")
def get_api_v1_profiles_profile_id(store: StoreDep, profile_id: str) -> JSONResponse:
    row = _get_profile_or_404(store, profile_id)
    return JSONResponse(profile_read(row),
                        headers={"ETag": store.config_revision()})


@router.patch("/api/v1/profiles/{profile_id}")
def patch_api_v1_profiles_profile_id(
        request: Request, store: StoreDep, profile_id: str, body: dict) -> JSONResponse:
    require_if_match(request)
    row = _get_profile_or_404(store, profile_id)
    if not isinstance(body, dict):
        raise ApiError(422, "Profile patch must be a JSON object.")
    if any(v is None for v in body.values()):
        raise ApiError(422, "Explicit null values are not allowed in updates.")
    _validate_body(store, body)
    data = json.loads(row["data"] or "{}")
    fields: dict = {}
    for k, v in body.items():
        if k in ("id", "created_at"):
            continue
        if k == "updated_at":
            continue
        (fields if k in ("name", "is_active") else data)[k] = v
    data["updated_at"] = now_iso()
    update = {"data": data}
    if "name" in fields:
        update["name"] = fields["name"]
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.update(int(profile_id), update)
        if "is_active" in fields:
            if fields["is_active"]:
                store.profiles.set_active(int(profile_id))
            else:
                store.profiles.update(int(profile_id), {"active": 0})
        revision = store.bump_revision()
    return JSONResponse(profile_read(store.profiles.get(int(profile_id))),
                        headers={"ETag": revision})


@router.delete("/api/v1/profiles/{profile_id}", status_code=204)
def delete_api_v1_profiles_profile_id(
        request: Request, response: Response, store: StoreDep, profile_id: str) -> None:
    require_if_match(request)
    _get_profile_or_404(store, profile_id)
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.delete(int(profile_id))
        response.headers["ETag"] = store.bump_revision()


@router.post("/api/v1/profiles/{profile_id}/activate")
def post_api_v1_profiles_profile_id_activate(
        request: Request, store: StoreDep, profile_id: str) -> JSONResponse:
    require_if_match(request)
    _get_profile_or_404(store, profile_id)
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.set_active(int(profile_id))
        revision = store.bump_revision()
    return JSONResponse(profile_read(store.profiles.get(int(profile_id))),
                        headers={"ETag": revision})

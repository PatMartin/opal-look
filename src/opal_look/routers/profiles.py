"""Profile endpoints (kernel OpalProfile/Create/Patch): portable namespaced
profile documents with shared + per-module compartments. Look's own
compartment is an explicit empty schema; foreign compartments are preserved
verbatim through reads, own-compartment edits and config save/load."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..profiles import (
    OWN_COMPARTMENT,
    profile_read,
    validate_modules,
    validate_shared,
)
from ..timeutil import now_iso

router = APIRouter()

_CREATE_FIELDS = {"id", "name", "description", "is_active", "shared", "modules"}
_PATCH_FIELDS = {"name", "description", "is_active", "shared", "modules"}


def _get_profile_or_404(store, profile_id: str):
    row = store.profiles.get(profile_id)
    if row is None:
        raise ApiError(404, f"Unknown profile: {profile_id}")
    return row


def _check_name(name) -> None:
    if not isinstance(name, str) or not name or len(name) > 100:
        raise ApiError(422, "Profile 'name' must be a string of 1-100 chars.")


@router.get("/api/v1/profile/")
def get_api_v1_profiles(store: StoreDep) -> JSONResponse:
    return JSONResponse([profile_read(r) for r in store.profiles.list()],
                        headers={"ETag": store.config_revision()})


@router.post("/api/v1/profile/", status_code=201)
def post_api_v1_profiles(request: Request, store: StoreDep, body: dict) -> JSONResponse:
    require_if_match(request)
    if not isinstance(body, dict):
        raise ApiError(422, "Profile body must be a JSON object.")
    unknown = set(body) - _CREATE_FIELDS
    if unknown:
        raise ApiError(422, f"Unknown profile fields: {sorted(unknown)}.")
    if "name" not in body:
        raise ApiError(422, "Profile 'name' is required.")
    _check_name(body["name"])
    if "id" in body and (not isinstance(body["id"], str) or not body["id"]):
        raise ApiError(422, "Profile 'id' must be a non-empty string.")
    if "description" in body and body["description"] is not None \
            and not isinstance(body["description"], str):
        raise ApiError(422, "Profile 'description' must be a string or null.")
    if "is_active" in body and not isinstance(body["is_active"], bool):
        raise ApiError(422, "is_active must be a boolean.")
    validate_shared(body.get("shared"))
    validate_modules(body.get("modules"), patch=False)

    pid = body.get("id") or f"p-{secrets.token_hex(6)}"
    now = now_iso()
    fields = {
        "profile_id": pid,
        "name": body["name"],
        "description": body.get("description"),
        "is_active": bool(body.get("is_active")),
        "shared": body.get("shared") or {},
        "modules": body.get("modules") or {},
        "created_at": now,
        "updated_at": now,
    }
    with store.write_txn():
        check_if_match(request, store)
        if store.profiles.get(pid) is not None:
            raise ApiError(409, f"Profile {pid!r} already exists.")
        store.profiles.insert(fields)
        if fields["is_active"]:
            store.profiles.set_active(pid)
        revision = store.bump_revision()
    return JSONResponse(profile_read(store.profiles.get(pid)),
                        status_code=201,
                        headers={"ETag": revision,
                                 "Location": f"/api/v1/profile/{pid}"})


@router.get("/api/v1/profile/{profile_id}")
def get_api_v1_profiles_profile_id(store: StoreDep, profile_id: str) -> JSONResponse:
    row = _get_profile_or_404(store, profile_id)
    return JSONResponse(profile_read(row),
                        headers={"ETag": store.config_revision()})


@router.patch("/api/v1/profile/{profile_id}")
def patch_api_v1_profiles_profile_id(
        request: Request, store: StoreDep, profile_id: str, body: dict) -> JSONResponse:
    require_if_match(request)
    row = _get_profile_or_404(store, profile_id)
    if not isinstance(body, dict):
        raise ApiError(422, "Profile patch must be a JSON object.")
    if not body:
        raise ApiError(422, "Empty profile patches are not allowed.")
    unknown = set(body) - _PATCH_FIELDS
    if unknown:
        raise ApiError(422, f"Unknown profile patch fields: {sorted(unknown)}.")
    if "name" in body:
        if body["name"] is None:
            raise ApiError(422, "Profile 'name' may not be null.")
        _check_name(body["name"])
    if "description" in body and body["description"] is not None \
            and not isinstance(body["description"], str):
        raise ApiError(422, "Profile 'description' must be a string or null.")
    if "is_active" in body and not isinstance(body["is_active"], bool):
        raise ApiError(422, "is_active must be a boolean.")
    validate_shared(body.get("shared"))
    validate_modules(body.get("modules"), patch=True)

    update: dict = {}
    if "name" in body:
        update["name"] = body["name"]
    if "description" in body:
        update["description"] = body["description"]
    # `shared` and the own compartment are closed-empty today: a supplied {}
    # merges to a no-op; field-wise merge lands here when fields exist.
    update["updated_at"] = now_iso()
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.update(profile_id, update)
        if body.get("is_active"):
            # True activates; false leaves the local selection unchanged.
            store.profiles.set_active(profile_id)
        revision = store.bump_revision()
    return JSONResponse(profile_read(store.profiles.get(profile_id)),
                        headers={"ETag": revision})


@router.delete("/api/v1/profile/{profile_id}", status_code=204)
def delete_api_v1_profiles_profile_id(
        request: Request, response: Response, store: StoreDep, profile_id: str) -> None:
    require_if_match(request)
    _get_profile_or_404(store, profile_id)
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.delete(profile_id)
        response.headers["ETag"] = store.bump_revision()


@router.post("/api/v1/profile/{profile_id}/activate")
def post_api_v1_profiles_profile_id_activate(
        request: Request, store: StoreDep, profile_id: str) -> JSONResponse:
    require_if_match(request)
    _get_profile_or_404(store, profile_id)
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.set_active(profile_id)
        revision = store.bump_revision()
    return JSONResponse(profile_read(store.profiles.get(profile_id)),
                        headers={"ETag": revision})

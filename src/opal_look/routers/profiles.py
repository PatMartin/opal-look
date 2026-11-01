"""Profile endpoints: CRUD, activation, validation."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..engines import model_read
from ..errors import ApiError
from ..precondition import check_if_match
from ..profiles import (
    profile_errors,
    profile_read,
    resolve_settings,
    supplied_settings_keys,
)
from ..refs import nonterminal_sessions_referencing
from ..schemas import ProfileCreate, ProfileUpdate, reject_null_fields
from ..store import Store

router = APIRouter()


def _get_profile_or_404(store: Store, profile_id: int):
    row = store.profiles.get(profile_id)
    if row is None:
        raise ApiError(404, f"Unknown profile: {profile_id}")
    return row


def _model_or_404(store: Store, model_id: str):
    row = store.models.get(model_id)
    if row is None:
        raise ApiError(404, f"Unknown model: {model_id!r}")
    return row


def _check_profile(
    store: Store, model_id: str, task: str, supplied: dict, resolved: dict
) -> sqlite3.Row:
    """404 on unknown model; 422 on incompatibility. Returns the model row."""
    model_row = _model_or_404(store, model_id)
    errors, _ = profile_errors(store, model_row, task, supplied, resolved)
    if errors:
        raise ApiError(422, "Profile is incompatible with the referenced model.", details=errors)
    return model_row


def _session_refs(store: Store, profile_id: int) -> None:
    if nonterminal_sessions_referencing(store, "profile", str(profile_id)):
        raise ApiError(409, f"Profile {profile_id} is referenced by a nonterminal session.")


@router.get("/api/v1/profiles/")
def get_api_v1_profiles(request: Request, store: StoreDep) -> JSONResponse:
    body = [profile_read(row) for row in store.profiles.list()]
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.post("/api/v1/profiles/", status_code=201)
def post_api_v1_profiles(request: Request, store: StoreDep, profile: ProfileCreate) -> JSONResponse:
    supplied = supplied_settings_keys(profile.settings)
    resolved = resolve_settings(profile.task, supplied)
    _check_profile(store, profile.model_id, profile.task, supplied, resolved)

    with store.write_txn():
        check_if_match(request, store)
        active = store.profiles.count() == 0
        profile_id = store.profiles.insert(
            profile.name, profile.model_id, profile.task, resolved, active
        )
        revision = store.bump_revision()
    row = store.profiles.get(profile_id)
    return JSONResponse(
        profile_read(row),
        status_code=201,
        headers={"ETag": revision, "Location": f"/api/v1/profiles/{profile_id}"},
    )


@router.get("/api/v1/profiles/{profile_id}")
def get_api_v1_profiles_profile_id(
    request: Request, store: StoreDep, profile_id: int = Path(ge=1)
) -> JSONResponse:
    row = _get_profile_or_404(store, profile_id)
    return JSONResponse(profile_read(row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/profiles/{profile_id}")
def patch_api_v1_profiles_profile_id(
    request: Request,
    store: StoreDep,
    patch: ProfileUpdate,
    profile_id: int = Path(ge=1, le=9223372036854775807),
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    reject_null_fields(supplied)

    check_if_match(request, store)
    row = _get_profile_or_404(store, profile_id)
    task = supplied.get("task") or row["task"]
    model_id = supplied.get("model_id") or row["model_id"]
    settings_supplied = supplied_settings_keys(patch.settings)
    resolved = resolve_settings(
        task, settings_supplied if "settings" in supplied else json.loads(row["settings"])
    )

    _check_profile(store, model_id, task, settings_supplied, resolved)
    _session_refs(store, profile_id)

    fields = {k: v for k, v in supplied.items() if k != "settings"}
    if "settings" in supplied:
        fields["settings"] = resolved

    with store.write_txn():
        check_if_match(request, store)
        if fields:
            store.profiles.update(profile_id, fields)
        revision = store.bump_revision()
    row = store.profiles.get(profile_id)
    return JSONResponse(profile_read(row), headers={"ETag": revision})


@router.delete("/api/v1/profiles/{profile_id}", status_code=204)
def delete_api_v1_profiles_profile_id(
    request: Request, response: Response, store: StoreDep,
    profile_id: int = Path(ge=1, le=9223372036854775807)
) -> None:
    check_if_match(request, store)
    row = _get_profile_or_404(store, profile_id)
    if row["active"]:
        raise ApiError(409, "Cannot delete the active profile; activate another first.")
    _session_refs(store, profile_id)
    with store.write_txn():
        check_if_match(request, store)
        store.profiles.delete(profile_id)
        response.headers["ETag"] = store.bump_revision()


@router.post("/api/v1/profiles/{profile_id}/validate")
def post_api_v1_profiles_profile_id_validate(
    request: Request, store: StoreDep, profile_id: int = Path(ge=1)
) -> dict:
    row = _get_profile_or_404(store, profile_id)
    read = profile_read(row)
    model_row = store.models.get(read["model_id"])
    if model_row is None:
        return {
            "valid": False,
            "errors": [f"model {read['model_id']!r} is no longer registered"],
            "warnings": [],
            "details": {"model_id": read["model_id"], "task": read["task"]},
        }
    errors, warnings = profile_errors(store, model_row, read["task"], {}, read["settings"])
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "details": {
            "model_id": read["model_id"],
            "engine_id": model_read(store, model_row)["engine_id"],
            "task": read["task"],
        },
    }


@router.post("/api/v1/profiles/{profile_id}/activate")
def post_api_v1_profiles_profile_id_activate(
    request: Request, store: StoreDep,
    profile_id: int = Path(ge=1, le=9223372036854775807)
) -> JSONResponse:
    check_if_match(request, store)
    row = _get_profile_or_404(store, profile_id)
    read = profile_read(row)
    # Activation re-checks current compatibility; runtime unavailability is OK.
    _check_profile(store, read["model_id"], read["task"], {}, read["settings"])

    with store.write_txn():
        check_if_match(request, store)
        store.profiles.set_active(profile_id)
        revision = store.bump_revision()
    row = store.profiles.get(profile_id)
    return JSONResponse(profile_read(row), headers={"ETag": revision})

"""Persona catalog endpoints (kernel persona_collection/item/validate).

Local catalog only: Look has no resolvable bindings, so `voice_id` is an
opaque reference; /validate checks the record's registered identity and
enabled state. If-Match on the configuration revision guards catalog
(create) and record (patch/delete) mutations."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..personas import check_persona_fields, check_persona_id, persona_read
from ..precondition import check_if_match, require_if_match
from ..timeutil import now_iso

router = APIRouter()

_CREATE_FIELDS = {"persona_id", "name", "description", "voice_id", "enabled"}
_UPDATE_FIELDS = {"name", "description", "voice_id", "enabled"}


def _get_persona_or_404(store, persona_id: str):
    row = store.personas.get(persona_id)
    if row is None:
        raise ApiError(404, f"Unknown persona: {persona_id}")
    return row


@router.get("/api/v1/persona/")
def get_api_v1_personas(store: StoreDep,
                        enabled: bool | None = None) -> JSONResponse:
    rows = store.personas.list(enabled=enabled)
    return JSONResponse([persona_read(r) for r in rows],
                        headers={"ETag": store.config_revision()})


@router.post("/api/v1/persona/", status_code=201)
def post_api_v1_personas(request: Request, store: StoreDep,
                         body: dict) -> JSONResponse:
    require_if_match(request)
    if not isinstance(body, dict):
        raise ApiError(422, "Persona body must be a JSON object.")
    unknown = set(body) - _CREATE_FIELDS
    if unknown:
        raise ApiError(422, f"Unknown persona fields: {sorted(unknown)}.")
    missing = {"persona_id", "name"} - set(body)
    if missing:
        raise ApiError(422, f"Missing persona fields: {sorted(missing)}.")
    check_persona_id(body["persona_id"])
    check_persona_fields(body, partial=False)

    pid = body["persona_id"]
    now = now_iso()
    fields = {
        "persona_id": pid,
        "name": body["name"],
        "description": body.get("description"),
        "voice_id": body.get("voice_id"),
        "enabled": body.get("enabled", True),
        "origin": "local",
        "created_at": now,
        "updated_at": now,
    }
    with store.write_txn():
        check_if_match(request, store)
        if store.personas.get(pid) is not None:
            raise ApiError(409, f"Persona {pid!r} already exists.")
        store.personas.insert(fields)
        revision = store.bump_revision()
    return JSONResponse(persona_read(store.personas.get(pid)),
                        status_code=201,
                        headers={"ETag": revision,
                                 "Location": f"/api/v1/persona/{pid}"})


@router.get("/api/v1/persona/{persona_id}")
def get_api_v1_personas_persona_id(store: StoreDep,
                                   persona_id: str) -> JSONResponse:
    row = _get_persona_or_404(store, persona_id)
    return JSONResponse(persona_read(row),
                        headers={"ETag": store.config_revision()})


@router.patch("/api/v1/persona/{persona_id}")
def patch_api_v1_personas_persona_id(
        request: Request, store: StoreDep, persona_id: str,
        body: dict) -> JSONResponse:
    require_if_match(request)
    _get_persona_or_404(store, persona_id)
    if not isinstance(body, dict):
        raise ApiError(422, "Persona patch must be a JSON object.")
    if not body:
        raise ApiError(422, "Empty persona patches are not allowed.")
    unknown = set(body) - _UPDATE_FIELDS
    if unknown:
        raise ApiError(422, f"Unknown persona patch fields: {sorted(unknown)}.")
    check_persona_fields(body, partial=True)

    update = {k: body[k] for k in body}  # null clears nullable fields
    update["updated_at"] = now_iso()
    with store.write_txn():
        check_if_match(request, store)
        store.personas.update(persona_id, update)
        revision = store.bump_revision()
    return JSONResponse(persona_read(store.personas.get(persona_id)),
                        headers={"ETag": revision})


@router.delete("/api/v1/persona/{persona_id}", status_code=204)
def delete_api_v1_personas_persona_id(
        request: Request, response: Response, store: StoreDep,
        persona_id: str) -> None:
    require_if_match(request)
    _get_persona_or_404(store, persona_id)
    with store.write_txn():
        check_if_match(request, store)
        store.personas.delete(persona_id)
        response.headers["ETag"] = store.bump_revision()


@router.post("/api/v1/persona/{persona_id}/validate")
def post_api_v1_personas_persona_id_validate(
        request: Request, store: StoreDep, persona_id: str) -> JSONResponse:
    row = _get_persona_or_404(store, persona_id)
    record = persona_read(row)
    errors, warnings = [], []
    if not record["enabled"]:
        errors.append({
            "code": "persona_disabled",
            "path": "enabled",
            "message": f"Persona {persona_id!r} is disabled.",
        })
    if record["voice_id"]:
        warnings.append({
            "code": "binding_unresolvable",
            "path": "voice_id",
            "message": "opal-look cannot resolve voice bindings; "
                       "the reference is opaque to this service.",
        })
    return JSONResponse({
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "details": {"persona_id": persona_id,
                    "checked": ["identity", "enabled"]},
    }, headers={"ETag": store.config_revision()})

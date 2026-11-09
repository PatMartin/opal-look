"""Persona endpoints (v1.6): named observer identities with optional
OPAL Say voice bindings."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..repositories.personas import persona_read
from ..schemas import IDENTIFIER_PATTERN
from ..store import Store

router = APIRouter()


class PersonaCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    persona_id: str = Field(pattern=IDENTIFIER_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    voice_id: str | None = Field(default=None, min_length=1)
    enabled: bool = Field(default=True)


class PersonaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    voice_id: str | None = Field(default=None, min_length=1)
    enabled: bool | None = Field(default=None)


def _issue(path: str, message: str, code: str = "invalid",
           severity: str = "error") -> dict:
    return {"path": path, "code": code, "message": message,
            "severity": severity}


def _get_persona_or_404(store: Store, persona_id: str):
    row = store.personas.get(persona_id)
    if row is None:
        raise ApiError(404, f"Unknown persona: {persona_id!r}")
    return row


@router.get("/api/v1/persona/")
def get_api_v1_persona(store: StoreDep, enabled: bool | None = None) -> JSONResponse:
    rows = store.personas.list(enabled=enabled)
    return JSONResponse([persona_read(r) for r in rows],
                        headers={"ETag": store.config_revision()})


@router.post("/api/v1/persona/", status_code=201)
def post_api_v1_persona(request: Request, store: StoreDep,
                      body: PersonaCreate) -> JSONResponse:
    require_if_match(request)
    with store.write_txn():
        check_if_match(request, store)
        try:
            store.personas.insert(body.model_dump())
        except sqlite3.IntegrityError:
            raise ApiError(409, f"The requested persona_id is already "
                                f"registered: {body.persona_id!r}")
        revision = store.bump_revision()
    return JSONResponse(
        persona_read(store.personas.get(body.persona_id)),
        status_code=201,
        headers={"ETag": revision,
                 "Location": f"/api/v1/persona/{body.persona_id}"})


@router.post("/api/v1/persona/{persona_id}/validate")
def post_api_v1_persona_validate(store: StoreDep, persona_id: str) -> dict:
    """OpalValidationReport: registered + enabled + bindings resolvable."""
    row = _get_persona_or_404(store, persona_id)
    issues: list[dict] = []
    if not row["enabled"]:
        issues.append(_issue("enabled", "persona is disabled",
                             code="persona_disabled"))
    if row["voice_id"] is not None and not str(row["voice_id"]).strip():
        issues.append(_issue("voice_id", "voice binding is not a usable "
                                         "identifier", code="unresolvable_binding"))
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] != "error"]
    return {"valid": not errors, "issues": issues,
            "errors": errors, "warnings": warnings}


@router.get("/api/v1/persona/{persona_id}")
def get_api_v1_persona_persona_id(store: StoreDep, persona_id: str) -> JSONResponse:
    return JSONResponse(persona_read(_get_persona_or_404(store, persona_id)),
                        headers={"ETag": store.config_revision()})


@router.patch("/api/v1/persona/{persona_id}")
def patch_api_v1_persona_persona_id(
    request: Request, store: StoreDep, persona_id: str, body: PersonaUpdate
) -> JSONResponse:
    require_if_match(request)
    _get_persona_or_404(store, persona_id)
    supplied = body.model_dump(exclude_unset=True)
    if not supplied:
        raise ApiError(422, "Empty persona patches are not allowed.")
    if supplied.get("name") is None and "name" in supplied:
        raise ApiError(422, "Explicit null is not allowed for 'name'.")
    if "enabled" in supplied and supplied["enabled"] is None:
        raise ApiError(422, "Explicit null is not allowed for 'enabled'.")
    with store.write_txn():
        check_if_match(request, store)
        store.personas.update(persona_id, supplied)
        revision = store.bump_revision()
    return JSONResponse(persona_read(store.personas.get(persona_id)),
                        headers={"ETag": revision})


@router.delete("/api/v1/persona/{persona_id}", status_code=204)
def delete_api_v1_persona_persona_id(
    request: Request, response: Response, store: StoreDep, persona_id: str
) -> None:
    require_if_match(request)
    _get_persona_or_404(store, persona_id)
    with store.write_txn():
        check_if_match(request, store)
        store.personas.delete(persona_id)
        response.headers["ETag"] = store.bump_revision()

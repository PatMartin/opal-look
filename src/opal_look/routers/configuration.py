"""v1.5 /configuration/export|validate|import (step 24)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..configuration import (
    apply_import, build_export, validate_configuration,
)
from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..schemas import ConfigurationImport

router = APIRouter()


@router.get("/api/v1/configuration/export")
def get_api_v1_configuration_export(store: StoreDep) -> dict:
    """Logical desired state only: redacted locators, no credentials,
    no runtime state (media/observations/jobs/recordings)."""
    return build_export(store)


@router.post("/api/v1/configuration/validate")
def post_api_v1_configuration_validate(store: StoreDep, body: dict) -> dict:
    """Non-mutating validation: concrete issues, never writes."""
    issues = validate_configuration(store, body or {}, None)
    return {"valid": not any(i["severity"] == "error" for i in issues),
            "issues": issues}


@router.post("/api/v1/configuration/import")
def post_api_v1_configuration_import(
    request: Request, store: StoreDep, body: ConfigurationImport
) -> dict:
    require_if_match(request)
    if body.mode != "replace":
        raise ApiError(422, f"Unsupported import mode: {body.mode!r}.")
    bindings = {
        k: v.model_dump() for k, v in (body.source_bindings or {}).items()
    }
    config = body.configuration
    issues = validate_configuration(store, config, bindings)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        raise ApiError(422, "Configuration is invalid: "
                            + "; ".join(i["message"] for i in errors[:4]),
                       details={"issues": issues})
    with store.write_txn():
        check_if_match(request, store)
        apply_import(store, request, config, bindings)
        store.bump_revision()
    return {"valid": True,
            "issues": [i for i in issues if i["severity"] != "error"]}

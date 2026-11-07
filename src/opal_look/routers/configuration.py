"""v1.5 /configuration/export|validate|import (kernel shapes)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..configuration import (
    apply_import, build_export, validate_configuration,
)
from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match

router = APIRouter()

_SECTIONS = ("settings", "engines", "profiles", "models", "sources",
             "pipelines", "zones", "rules", "monitors")


def _report(issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Kernel OpalValidationReport: valid flag plus sorted diagnostics."""
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] != "error"]
    return {
        "valid": not errors,
        "issues": issues,
        "errors": errors,
        "warnings": warnings,
    }


def _unwrap(body: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Kernel body is the OpalConfigExport bundle itself; a legacy
    {configuration, source_bindings} wrapper is still accepted."""
    if body is None:
        raise ApiError(422, "A configuration bundle body is required.")
    if not isinstance(body, dict):
        raise ApiError(422, "Configuration bundle must be a JSON object.")
    if isinstance(body.get("configuration"), dict):
        legacy = body
        return legacy["configuration"], (legacy.get("source_bindings") or {})
    return body, (body.get("source_bindings") or {})


@router.get("/api/v1/configuration/export")
def get_api_v1_configuration_export(store: StoreDep) -> dict:
    """OpalConfigExport: logical desired state only — redacted locators,
    no credentials, no runtime state (media/observations/jobs/recordings)."""
    return build_export(store)


@router.post("/api/v1/configuration/validate")
def post_api_v1_configuration_validate(store: StoreDep, body: dict) -> dict:
    """OpalValidationReport: non-mutating issues, never writes."""
    config, bindings = _unwrap(body)
    return _report(validate_configuration(store, config, bindings))


@router.post("/api/v1/configuration/import")
def post_api_v1_configuration_import(
    request: Request, store: StoreDep, body: dict | None
) -> JSONResponse:
    """OpalImportResult: atomic replace under If-Match."""
    require_if_match(request)
    config, bindings = _unwrap(body)
    issues = validate_configuration(store, config, bindings)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        raise ApiError(422, "Configuration is invalid: "
                            + "; ".join(i["message"] for i in errors[:4]),
                       details={"issues": issues})
    with store.write_txn():
        check_if_match(request, store)
        apply_import(store, request, config, bindings)
        revision = store.bump_revision()
    counts = {
        section: len(config.get(section) or [])
        for section in _SECTIONS if section != "settings"
    }
    counts["settings"] = len(config.get("settings") or {})
    result = {
        "success": True,
        "status": "imported",
        "message": None,
        "counts": counts,
        "warnings": [i for i in issues if i["severity"] != "error"],
        "validation": _report(issues),
        "revision": revision,
        "pending_restart": False,
    }
    return JSONResponse(result, headers={"ETag": revision})

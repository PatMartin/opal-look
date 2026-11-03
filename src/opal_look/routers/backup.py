"""Backup endpoints: export/import/validate + server-managed backup files."""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..backup import (
    backup_dir, backup_read, check_backup_filename, export_config, import_config,
    validate_config,
)
from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match

router = APIRouter()


@router.get("/api/v1/backup/export")
def get_api_v1_backup_export(request: Request, store: StoreDep) -> JSONResponse:
    return JSONResponse(export_config(store),
                      headers={"ETag": store.config_revision()})


def _import_common(request, store, payload) -> JSONResponse:
    with store.write_txn():
        check_if_match(request, store)
        warnings = import_config(store, payload)
        revision = store.bump_revision()
    return JSONResponse(
        {"success": True,
         "validation": {"valid": True, "errors": [], "warnings": warnings,
                        "details": {}},
         "message": "Configuration imported."},
        headers={"ETag": revision},
    )


_REQUIRED_KEYS = {"version", "exported_at", "engines", "models", "sources",
                  "profiles", "settings"}


def _require_export(body) -> dict:
    if not isinstance(body, dict) or not _REQUIRED_KEYS.issubset(body):
        raise ApiError(422, "Request body must be a complete ConfigExport object.")
    return body


@router.post("/api/v1/backup/import")
def post_api_v1_backup_import(request: Request, store: StoreDep, body: dict) -> JSONResponse:
    payload = _require_export(body)
    require_if_match(request)
    return _import_common(request, store, payload)


@router.get("/api/v1/backup/validate")
def get_api_v1_backup_validate(request: Request, store: StoreDep) -> dict:
    errors, warnings = validate_config(store, export_config(store))
    return {"valid": not errors, "errors": errors, "warnings": warnings, "details": {}}


@router.post("/api/v1/backup/validate")
def post_api_v1_backup_validate(request: Request, store: StoreDep, body: dict) -> dict:
    payload = _require_export(body)
    try:
        errors, warnings = validate_config(store, payload)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(422, f"Malformed backup: {exc}")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "details": {}}


@router.get("/api/v1/backup/list")
def get_api_v1_backup_list(request: Request, store: StoreDep) -> list:
    d = backup_dir(store)
    return sorted(
        (backup_read(p) for p in d.glob("*.json")),
        key=lambda b: b["filename"], reverse=True,
    )


@router.post("/api/v1/backup/create", status_code=201)
def post_api_v1_backup_create(request: Request, store: StoreDep) -> JSONResponse:
    filename = f"backup-{secrets.token_hex(6)}.json"
    path = backup_dir(store) / filename
    path.write_text(json.dumps(export_config(store), indent=2))
    return JSONResponse(
        {"filename": filename, "message": "Backup created."}, status_code=201,
        headers={"Location": f"/api/v1/backup/download/{filename}"},
    )


def _backup_path(store, filename: str):
    check_backup_filename(filename)
    path = backup_dir(store) / filename
    if not path.is_file():
        raise ApiError(404, f"Unknown backup: {filename!r}")
    return path


@router.get("/api/v1/backup/download/{filename}")
def get_api_v1_backup_download_filename(request: Request, store: StoreDep, filename: str):
    return JSONResponse(json.loads(_backup_path(store, filename).read_text()))


@router.post("/api/v1/backup/restore/{filename}")
def post_api_v1_backup_restore_filename(request: Request, store: StoreDep, filename: str):
    path = _backup_path(store, filename)
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        raise ApiError(422, "Backup file is not valid JSON.")
    _require_export(payload)
    require_if_match(request)
    return _import_common(request, store, payload)


@router.delete("/api/v1/backup/{filename}", status_code=204)
def delete_api_v1_backup_filename(request: Request, store: StoreDep, filename: str) -> None:
    _backup_path(store, filename).unlink()

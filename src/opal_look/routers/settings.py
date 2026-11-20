"""Portable settings endpoints: whole-map GET and per-key GET/PUT/DELETE.

v0.1.0 retires the collection PATCH; writes are per-key only. Setting
records carry kernel provenance: `value` is the effective value after
environment/.env overlays, `configured_value` the persisted desired value,
`source` the winning layer (environment > dotenv > persisted > default).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match
from ..settings import (
    SETTINGS_KEYS,
    ServiceSettings,
    ServiceSettingsPatch,
    SingleSettingPut,
    effective_settings,
    env_overlays,
)

router = APIRouter()

_KEY_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)*$")


def _check_key_path(key: str) -> None:
    if not _KEY_PATH.match(key):
        raise ApiError(422, f"Invalid setting key path: {key!r}")


def _known_key(key: str) -> None:
    if key not in SETTINGS_KEYS:
        raise ApiError(404, f"Unknown setting key: {key!r}")


def _reject_nulls(values: dict) -> None:
    if any(value is None for value in values.values()):
        raise ApiError(422, "Null setting values are not allowed.")


def _setting_read(store, key: str) -> dict:
    """Kernel SettingRead: effective/configured/default plus provenance."""
    effective = effective_settings(store).model_dump(mode="json")
    override = store.settings.entry(key)
    overlays = env_overlays()
    from pydantic_core import PydanticUndefined
    default = ServiceSettings.model_fields[key].default
    default = None if default is PydanticUndefined else default
    if key in overlays:
        source = overlays[key]["source"]
    elif override is not None:
        source = "persisted"
    else:
        source = "default"
    warnings = []
    if source in ("environment", "dotenv") and override is not None:
        warnings.append({
            "code": f"masked_by_{source}",
            "path": key,
            "message": (f"The {source} overlay masks the persisted "
                        f"override for {key!r}."),
        })
    body = {
        "key": key,
        "value": effective[key],
        "configured_value": override["value"] if override else default,
        "default": default,
        "has_override": override is not None,
        "is_default": source == "default",
        "source": source,
        "restart_required": False,
        "pending_restart": False,
        "warnings": warnings,
    }
    if override and override.get("updated_at"):
        body["updated_at"] = override["updated_at"]
    return body


@router.get("/api/v1/setting/")
def get_api_v1_settings(request: Request, store: StoreDep) -> JSONResponse:
    body = effective_settings(store).model_dump(mode="json")
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.get("/api/v1/setting/{key}")
def get_look_setting(request: Request, store: StoreDep, key: str) -> JSONResponse:
    _check_key_path(key)
    _known_key(key)
    return JSONResponse(_setting_read(store, key),
                        headers={"ETag": store.config_revision()})


@router.put("/api/v1/setting/{key}")
def put_look_setting(
    request: Request, store: StoreDep, key: str, body: SingleSettingPut
) -> JSONResponse:
    _check_key_path(key)
    _known_key(key)
    try:
        validated = ServiceSettingsPatch.model_validate({key: body.value})
    except ValidationError as exc:
        raise ApiError(422, f"Invalid value for setting {key!r}.", details=exc.errors())
    value = validated.model_dump(exclude_unset=True)[key]
    _reject_nulls({key: value})

    with store.write_txn():
        check_if_match(request, store)
        store.settings.set(key, value)
        revision = store.bump_revision()
    return JSONResponse(_setting_read(store, key), headers={"ETag": revision})


@router.delete("/api/v1/setting/{key}", status_code=204)
def delete_look_setting(request: Request, response: Response, store: StoreDep, key: str) -> None:
    _check_key_path(key)
    _known_key(key)
    with store.write_txn():
        check_if_match(request, store)
        store.settings.delete(key)
        response.headers["ETag"] = store.bump_revision()

"""Portable settings endpoints: whole-map GET/PATCH and per-key GET/PUT/DELETE."""

from __future__ import annotations

import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..errors import ApiError
from ..precondition import check_if_match
from ..settings import (
    SETTINGS_KEYS,
    ServiceSettingsPatch,
    SingleSettingPut,
    effective_settings,
)

router = APIRouter()

_KEY_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)*$")


def _check_key_path(key: str) -> None:
    if not _KEY_PATH.match(key):
        raise ApiError(422, f"Invalid setting key path: {key!r}")


def _known_key(key: str) -> None:
    if key not in SETTINGS_KEYS:
        raise ApiError(404, f"Unknown setting key: {key!r}")


def _event_transport_check(request: Request, values: dict) -> None:
    if values.get("events_enabled") is True and not request.app.state.event_transport:
        raise ApiError(
            422,
            "Event transport is not provisioned; events_enabled cannot be set to true.",
        )


def _reject_nulls(values: dict) -> None:
    if any(value is None for value in values.values()):
        raise ApiError(422, "Null setting values are not allowed.")


@router.get("/api/v1/settings/")
def get_api_v1_settings(request: Request) -> JSONResponse:
    store = request.app.state.store
    body = effective_settings(store).model_dump(mode="json")
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.patch("/api/v1/settings/")
def patch_api_v1_settings(request: Request, patch: ServiceSettingsPatch) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    if not supplied:
        raise ApiError(422, "Empty settings patches are not allowed.")
    _reject_nulls(supplied)
    _event_transport_check(request, supplied)

    store = request.app.state.store
    with store.write_txn():
        check_if_match(request, store)
        for key, value in supplied.items():
            store.set_setting(key, value)
        revision = store.bump_revision()
    body = effective_settings(store).model_dump(mode="json")
    return JSONResponse(body, headers={"ETag": revision})


@router.get("/api/v1/settings/{key}")
def get_look_setting(request: Request, key: str) -> JSONResponse:
    _check_key_path(key)
    _known_key(key)
    store = request.app.state.store
    value = effective_settings(store).model_dump(mode="json")[key]
    return JSONResponse({"key": key, "value": value}, headers={"ETag": store.config_revision()})


@router.put("/api/v1/settings/{key}")
def put_look_setting(request: Request, key: str, body: SingleSettingPut) -> JSONResponse:
    _check_key_path(key)
    _known_key(key)
    try:
        validated = ServiceSettingsPatch.model_validate({key: body.value})
    except ValidationError as exc:
        raise ApiError(422, f"Invalid value for setting {key!r}.", details=exc.errors())
    value = validated.model_dump(exclude_unset=True)[key]
    _reject_nulls({key: value})
    _event_transport_check(request, {key: value})

    store = request.app.state.store
    with store.write_txn():
        check_if_match(request, store)
        store.set_setting(key, value)
        revision = store.bump_revision()
    effective = effective_settings(store).model_dump(mode="json")
    return JSONResponse({"key": key, "value": effective[key]}, headers={"ETag": revision})


@router.delete("/api/v1/settings/{key}", status_code=204)
def delete_look_setting(request: Request, response: Response, key: str) -> None:
    _check_key_path(key)
    _known_key(key)
    store = request.app.state.store
    with store.write_txn():
        check_if_match(request, store)
        store.delete_setting(key)
        response.headers["ETag"] = store.bump_revision()

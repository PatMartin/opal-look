"""Source registration endpoints + camera device discovery."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..refs import nonterminal_sessions_referencing
from ..schemas import IDENTIFIER_PATTERN, SourceCreate, SourcePatch, reject_null_fields
from ..sources import (
    check_locator,
    check_source_options,
    discover_cameras,
    missing_reference,
    source_read,
    validate_source,
)
from ..store import Store

router = APIRouter()


def _get_source_or_404(store: Store, source_id: str):
    row = store.sources.get(source_id)
    if row is None:
        raise ApiError(404, f"Unknown source: {source_id!r}")
    return row


def _check_source_fields(store: Store, source_type: str, locator: str, options: dict) -> None:
    errors = check_locator(source_type, locator) + check_source_options(source_type, options)
    if errors:
        raise ApiError(422, "Invalid source configuration.", details=errors)
    missing = missing_reference(store, source_type, locator)
    if missing:
        raise ApiError(404, missing)


def _session_refs(store: Store, source_id: str) -> None:
    if nonterminal_sessions_referencing(store, "source", source_id):
        raise ApiError(409, f"Source {source_id!r} is referenced by a nonterminal session.")


@router.get("/api/v1/sources/")
def get_api_v1_sources(
    request: Request,
    store: StoreDep,
    enabled: bool | None = Query(default=None),
) -> JSONResponse:
    body = [source_read(store, row) for row in store.sources.list(enabled=enabled)]
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.post("/api/v1/sources/", status_code=201)
def post_api_v1_sources(request: Request, store: StoreDep, source: SourceCreate) -> JSONResponse:
    if store.sources.get(source.id) is not None:
        raise ApiError(409, f"Source {source.id!r} already exists.")
    _check_source_fields(store, source.kind, source.locator, source.options)

    with store.write_txn():
        check_if_match(request, store)
        store.sources.insert({
            "source_id": source.id, "name": source.name, "type": source.kind,
            "locator": source.locator, "credential_ref": source.secret_ref,
            "enabled": source.enabled, "source_options": source.options,
            "zones": [z.model_dump() for z in source.zones],
        })
        revision = store.bump_revision()
    row = store.sources.get(source.id)
    return JSONResponse(
        source_read(store, row),
        status_code=201,
        headers={"ETag": revision, "Location": f"/api/v1/sources/{source.id}"},
    )


@router.get("/api/v1/sources/{source_id}")
def get_api_v1_sources_source_id(request: Request, store: StoreDep, source_id: str) -> JSONResponse:
    row = _get_source_or_404(store, source_id)
    return JSONResponse(source_read(store, row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/sources/{source_id}")
def patch_api_v1_sources_source_id(
    request: Request, store: StoreDep, source_id: str, patch: SourcePatch
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    reject_null_fields({k: v for k, v in supplied.items() if k != "secret_ref"})

    require_if_match(request)
    row = _get_source_or_404(store, source_id)
    stored_options = row["source_options"]
    if isinstance(stored_options, str):
        stored_options = json.loads(stored_options)
    merged = {
        "locator": supplied.get("locator") or row["locator"],
        "options": supplied.get("options") if "options" in supplied else stored_options,
    }
    _check_source_fields(store, row["type"], merged["locator"], merged["options"])
    _session_refs(store, source_id)

    fields = {}
    for api, col in (("name", "name"), ("locator", "locator"),
                     ("secret_ref", "credential_ref"), ("enabled", "enabled"),
                     ("options", "source_options"), ("zones", "zones")):
        if api in supplied:
            fields[col] = supplied[api]  # model_dump already yields plain dicts
    # zones replaces the whole collection atomically inside the txn.
    with store.write_txn():
        check_if_match(request, store)
        if fields:
            store.sources.update(source_id, fields)
        revision = store.bump_revision()
    row = store.sources.get(source_id)
    return JSONResponse(source_read(store, row), headers={"ETag": revision})


@router.delete("/api/v1/sources/{source_id}", status_code=204)
def delete_api_v1_sources_source_id(
    request: Request, response: Response, store: StoreDep, source_id: str
) -> None:
    require_if_match(request)
    _get_source_or_404(store, source_id)
    _session_refs(store, source_id)
    with store.write_txn():
        check_if_match(request, store)
        store.sources.delete(source_id)
        response.headers["ETag"] = store.bump_revision()


@router.post("/api/v1/sources/{source_id}/validate")
def post_api_v1_sources_source_id_validate(request: Request, store: StoreDep, source_id: str) -> dict:
    row = _get_source_or_404(store, source_id)
    return validate_source(store, row)


@router.get("/api/v1/devices/cameras/")
def get_api_v1_devices_cameras(request: Request) -> list:
    return discover_cameras()


# -- v1.5 runtime surfaces: status / probe / frame -----------------------------
# These are read-only operational endpoints: they never mutate configuration,
# never bump the revision, and never leak credentialed locators.


def _jpeg_bytes(image) -> bytes:
    import io

    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG")
    return buf.getvalue()


@router.get("/api/v1/sources/{source_id}/status")
def get_api_v1_sources_source_id_status(request: Request, store: StoreDep, source_id: str) -> dict:
    _get_source_or_404(store, source_id)
    from ..sessions import TERMINAL
    from ..timeutil import now_iso

    rows = store.sessions.page(now_iso(), 10**9, {"source_id": source_id}, None, 1000)
    active = [r for r in rows if r["state"] not in TERMINAL]
    return {
        "source_id": source_id,
        "connected": bool(active),
        "last_frame_at": None,
        "dropped_frames": sum(r["frames_dropped"] or 0 for r in rows),
    }


@router.post("/api/v1/sources/{source_id}/probe")
def post_api_v1_sources_source_id_probe(request: Request, store: StoreDep, source_id: str) -> dict:
    import os

    from ..capture import (
        CredentialUnavailable,
        capture_adapter_for,
        credentialed_locator,
    )
    from ..refs import media_exists

    row = _get_source_or_404(store, source_id)
    kind = row["type"]
    locator = row["locator"]
    warnings: list[str] = []
    details: dict = {}
    reachable = False

    if not row["enabled"]:
        warnings.append("source is disabled")
    elif kind == "rtsp":
        adapter = capture_adapter_for("rtsp")
        if adapter is None:
            warnings.append("no rtsp capture adapter installed")
        else:
            try:
                credentialed = credentialed_locator(locator, row["credential_ref"])
            except CredentialUnavailable:
                warnings.append("credential reference is not provisioned")
            else:
                result = adapter.probe_stream(
                    locator, json.loads(row["source_options"]), credentialed
                )
                reachable = bool(result.get("available"))
                details = {k: v for k, v in result.items() if k != "available"}
    elif kind == "media":
        reachable = media_exists(store, locator)
        details = {"media_id": locator}
    elif kind == "file":
        reachable = os.path.isfile(locator)
        if reachable:
            warnings.append("no video decoder installed")
    elif kind == "image":
        if not os.path.isfile(locator):
            details = {"message": "host path not found"}
        else:
            try:
                from PIL import Image

                with Image.open(locator) as im:
                    im.verify()
                reachable = True
            except Exception:
                details = {"message": "image file is not readable"}
    elif kind == "camera":
        warnings.append("no camera capture adapter installed")
    elif kind == "http":
        warnings.append("http sources are not probed")
    else:
        warnings.append(f"unknown source kind {kind!r}")
    return {
        "source_id": source_id,
        "reachable": reachable,
        "details": details,
        "warnings": warnings,
    }


@router.get("/api/v1/sources/{source_id}/frame")
def get_api_v1_sources_source_id_frame(request: Request, store: StoreDep, source_id: str) -> Response:
    import io
    import os

    from PIL import Image

    from ..capture import (
        CaptureError,
        CredentialUnavailable,
        capture_adapter_for,
        credentialed_locator,
    )
    from ..refs import media_exists

    row = _get_source_or_404(store, source_id)
    if not row["enabled"]:
        raise ApiError(503, "Source is disabled.")
    kind = row["type"]
    locator = row["locator"]

    if kind == "rtsp":
        adapter = capture_adapter_for("rtsp")
        if adapter is None:
            raise ApiError(503, "No rtsp capture adapter installed.")
        try:
            credentialed = credentialed_locator(locator, row["credential_ref"])
        except CredentialUnavailable as exc:
            raise ApiError(503, f"Credential unavailable: {exc}")
        try:
            image = adapter.grab(locator, json.loads(row["source_options"]), credentialed)
        except CaptureError as exc:
            raise ApiError(503, f"Frame capture failed: {exc}")
        return Response(_jpeg_bytes(image), media_type="image/jpeg")
    if kind == "media":
        if not media_exists(store, locator):
            raise ApiError(503, "Referenced media is unavailable.")
        media_row = store.media.get(locator)
        image = Image.open(media_row["path"])
        return Response(_jpeg_bytes(image), media_type="image/jpeg")
    if kind == "image":
        if not os.path.isfile(locator):
            raise ApiError(503, "Host path not found.")
        try:
            image = Image.open(locator)
            image.load()
        except Exception:
            raise ApiError(503, "Image file is not readable.")
        return Response(_jpeg_bytes(image), media_type="image/jpeg")
    if kind == "file":
        raise ApiError(503, "No video decoder installed for file sources.")
    if kind == "camera":
        raise ApiError(503, "No camera capture adapter installed.")
    raise ApiError(503, f"No frame capture path for source kind {kind!r}.")

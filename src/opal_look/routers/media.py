"""Uploaded media endpoints: upload, list (cursor), get, delete, download."""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..media import (
    detect_and_decode,
    is_expired,
    media_dir,
    media_read,
    sanitize_filename,
)
from ..pagination import decode_cursor, encode_cursor, filter_key
from ..refs import nonterminal_sessions_referencing
from ..settings import effective_settings
from ..timeutil import iso, now_iso, plus_hours

router = APIRouter()

_FKEY = filter_key({})


@router.post("/api/v1/media/", status_code=201)
async def post_api_v1_media(
    request: Request, store: StoreDep, file: UploadFile = File()
) -> JSONResponse:
    settings = effective_settings(store)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_upload_bytes:
        raise ApiError(413, "Upload exceeds the configured size limit.")
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise ApiError(413, "Upload exceeds the configured size limit.")

    decoded = detect_and_decode(data, settings.max_image_pixels)

    media_id = f"media-{secrets.token_hex(8)}"
    blob_dir = media_dir(store.data_dir)
    blob_path = blob_dir / media_id
    blob_path.write_bytes(data)

    created_at = now_iso()
    fields = {
        "media_id": media_id,
        "filename": sanitize_filename(file.filename),
        "kind": decoded["kind"],
        "content_type": decoded["content_type"],
        "size_bytes": len(data),
        "path": str(blob_path),
        "width": decoded["width"],
        "height": decoded["height"],
        "duration_ms": decoded["duration_ms"],
        "created_at": created_at,
        "expires_at": iso(plus_hours(settings.media_retention_hours)),
    }
    with store.write_txn():
        store.media.insert(fields)
    row = store.media.get(media_id)
    return JSONResponse(
        media_read(row),
        status_code=201,
        headers={"Location": f"/api/v1/media/{media_id}"},
    )


@router.get("/api/v1/media/")
def get_api_v1_media(
    request: Request,
    store: StoreDep,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None, min_length=1),
) -> dict:
    after, _, _ = decode_cursor(cursor, _FKEY)
    rows = store.media.page(now_iso(), after, limit)
    items = rows[:limit]
    has_more = len(rows) > limit
    next_cursor = (
        encode_cursor(_FKEY, [items[-1]["created_at"], items[-1]["media_id"]])
        if has_more
        else None
    )
    return {
        "items": [media_read(row) for row in items],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _get_media_or_404(store: StoreDep, media_id: str):
    row = store.media.get(media_id)
    if row is None:
        raise ApiError(404, f"Unknown media: {media_id!r}")
    if is_expired(row):
        raise ApiError(410, f"Media {media_id!r} has expired.", code="gone")
    return row


@router.get("/api/v1/media/{media_id}")
def get_api_v1_media_media_id(request: Request, store: StoreDep, media_id: str) -> dict:
    return media_read(_get_media_or_404(store, media_id))


@router.delete("/api/v1/media/{media_id}", status_code=204)
def delete_api_v1_media_media_id(request: Request, store: StoreDep, media_id: str) -> None:
    row = store.media.get(media_id)
    if row is None:
        raise ApiError(404, f"Unknown media: {media_id!r}")
    if nonterminal_sessions_referencing(store, "media", media_id):
        raise ApiError(409, f"Media {media_id!r} is pinned by an active session or analysis.")
    with store.write_txn():
        store.media.delete(media_id)
    try:
        Path(row["path"]).unlink(missing_ok=True)
    except OSError:
        pass


@router.get("/api/v1/media/{media_id}/content")
def get_api_v1_media_media_id_content(request: Request, store: StoreDep, media_id: str):
    row = _get_media_or_404(store, media_id)
    return FileResponse(row["path"], media_type=row["content_type"])

"""Retained snapshot endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..pagination import decode_cursor, encode_cursor, filter_key
from ..snapshots import snapshot_read
from ..timeutil import expired, now_iso

router = APIRouter()


@router.get("/api/v1/snapshots/")
def get_api_v1_snapshots(
    request: Request,
    store: StoreDep,
    result_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None, min_length=1),
) -> dict:
    fkey = filter_key({"result_id": result_id} if result_id else {})
    after, _, _ = decode_cursor(cursor, fkey)
    rows = store.snapshots.page(now_iso(), result_id, after, limit)
    items = rows[:limit]
    has_more = len(rows) > limit
    next_cursor = (
        encode_cursor(fkey, [items[-1]["created_at"], items[-1]["snapshot_id"]])
        if has_more
        else None
    )
    return {
        "items": [snapshot_read(row) for row in items],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _snapshot_or_404(store, snapshot_id: str):
    row = store.snapshots.get(snapshot_id)
    if row is None:
        raise ApiError(404, f"Unknown snapshot: {snapshot_id!r}")
    if expired(row["expires_at"]):
        raise ApiError(410, f"Snapshot {snapshot_id!r} has expired.", code="gone")
    return row


@router.get("/api/v1/snapshots/{snapshot_id}")
def get_api_v1_snapshots_snapshot_id(request: Request, store: StoreDep, snapshot_id: str) -> dict:
    return snapshot_read(_snapshot_or_404(store, snapshot_id))


@router.delete("/api/v1/snapshots/{snapshot_id}", status_code=204)
def delete_api_v1_snapshots_snapshot_id(request: Request, store: StoreDep, snapshot_id: str) -> None:
    row = store.snapshots.get(snapshot_id)
    if row is None:
        raise ApiError(404, f"Unknown snapshot: {snapshot_id!r}")
    with store.write_txn():
        store.snapshots.delete(snapshot_id)
    try:
        Path(row["path"]).unlink(missing_ok=True)
    except OSError:
        pass


@router.get("/api/v1/snapshots/{snapshot_id}/content")
def get_api_v1_snapshots_snapshot_id_content(request: Request, store: StoreDep, snapshot_id: str):
    row = _snapshot_or_404(store, snapshot_id)
    return FileResponse(row["path"], media_type="image/jpeg")

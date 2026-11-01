"""Result history endpoints + exact-frame snapshot capture."""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from ..dependencies import StoreDep
from ..errors import ApiError
from ..pagination import decode_cursor, encode_cursor, filter_key
from ..results import result_read
from ..schemas import Task
from ..settings import effective_settings
from ..snapshots import annotate, snapshot_read
from ..timeutil import iso, now_iso, parse_iso, utcnow, expired
from datetime import timedelta

router = APIRouter()


@router.get("/api/v1/results/")
def get_api_v1_results(
    request: Request,
    store: StoreDep,
    session_id: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
    task: Task | None = Query(default=None),
    class_label: str | None = Query(default=None),
    text: str | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None, min_length=1),
) -> dict:
    if class_label is not None and text is not None:
        raise ApiError(422, "class_label and text filters are incompatible.")
    if class_label is not None and task == "ocr":
        raise ApiError(422, "class_label filter is not valid for ocr results.")
    if text is not None and task is not None and task != "ocr":
        raise ApiError(422, "text filter applies only to ocr results.")

    filters = {
        "session_id": session_id, "source_id": source_id, "model_id": model_id,
        "task": task, "class_label": class_label, "text": text,
        "from": from_, "to": to,
    }
    fkey = filter_key({k: v for k, v in filters.items() if v is not None})
    after, bound, scanned = decode_cursor(cursor, fkey)
    if bound is None:
        bound = now_iso()

    budget = effective_settings(store).max_result_query_limit
    rows = store.results.page(now_iso(), bound, after, limit, filters)
    scanned += len(rows)
    if scanned > budget:
        raise ApiError(
            422, "Result query budget exceeded; narrow the filters.",
            code="result_query_budget_exceeded",
        )
    items = rows[:limit]
    has_more = len(rows) > limit
    next_cursor = (
        encode_cursor(fkey, [items[-1]["analyzed_at"], items[-1]["result_id"]], bound, scanned)
        if has_more
        else None
    )
    return {
        "items": [result_read(row) for row in items],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _stored_result_or_404(store, result_id: str):
    row = store.results.get(result_id)
    if row is None or not row["stored"]:
        raise ApiError(404, f"Unknown result: {result_id!r}")
    if expired(row["expires_at"]):
        raise ApiError(410, f"Result {result_id!r} has expired.", code="gone")
    return row


@router.get("/api/v1/results/{result_id}")
def get_api_v1_results_result_id(request: Request, store: StoreDep, result_id: str) -> dict:
    return result_read(_stored_result_or_404(store, result_id))


@router.delete("/api/v1/results/{result_id}", status_code=204)
def delete_api_v1_results_result_id(request: Request, store: StoreDep, result_id: str) -> None:
    if store.results.get(result_id) is None:
        raise ApiError(404, f"Unknown result: {result_id!r}")
    with store.write_txn():
        store.results.delete(result_id)


class _SnapshotBody:
    pass


@router.post("/api/v1/results/{result_id}/snapshot")
def post_api_v1_results_result_id_snapshot(
    request: Request, store: StoreDep, result_id: str, body: dict
):
    annotated = bool((body or {}).get("annotated", False))
    retain = bool((body or {}).get("retain", False))
    if not isinstance(annotated, bool) or not isinstance(retain, bool) or set(body) - {"annotated", "retain"}:
        raise ApiError(422, "Invalid snapshot request body.")

    # Stored history or ephemeral cached result.
    row = store.results.get(result_id)
    result = result_read(row) if row is not None and row["stored"] else None
    entry = request.app.state.frame_cache.get(result_id)
    if result is None:
        if entry is None:
            raise ApiError(404, f"Unknown result: {result_id!r}")
        result = entry.result
    if entry is None:
        raise ApiError(409, "Exact analyzed frame is no longer cached.", code="frame_unavailable")

    image = annotate(entry.image, result) if annotated else entry.image
    if not retain:
        import io

        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        return Response(content=buf.getvalue(), media_type="image/jpeg")

    settings = effective_settings(store)
    snapshot_id = f"snap-{secrets.token_hex(8)}"
    snap_dir = Path(store.data_dir) / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / f"{snapshot_id}.jpg"
    image.save(path, format="JPEG")
    fields = {
        "snapshot_id": snapshot_id,
        "result_id": result_id,
        "annotated": annotated,
        "path": str(path),
        "width": image.width,
        "height": image.height,
        "created_at": now_iso(),
        "expires_at": iso(utcnow() + timedelta(hours=settings.snapshot_retention_hours)),
    }
    with store.write_txn():
        store.snapshots.insert(fields)
    return JSONResponse(
        snapshot_read(store.snapshots.get(snapshot_id)),
        status_code=201,
        headers={"Location": f"/api/v1/snapshots/{snapshot_id}"},
    )

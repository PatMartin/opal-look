"""Capture endpoints (upstream): on-demand frame captures as resources."""

from __future__ import annotations

import io
import secrets
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..analysis import _grab_live_frame
from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..settings import effective_settings
from ..snapshots import annotate, capture_read
from ..sources import LIVE_TYPES
from ..store import Store
from ..timeutil import iso, now_iso, utcnow

router = APIRouter()


class CaptureCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    retain: bool
    annotate: bool = Field(default=False)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    observation_id: str | None = Field(default=None, min_length=1, max_length=128)


def _source_or_404(store: Store, source_id: str):
    row = store.sources.get(source_id)
    if row is None:
        raise ApiError(404, f"Unknown source: {source_id!r}")
    return row


def _capture_or_404(store: Store, capture_id: str):
    row = store.snapshots.get(capture_id)
    if row is None:
        raise ApiError(404, f"Unknown capture: {capture_id!r}")
    return row


def _grab_frame(request: Request, store: Store, source_row,
              session_id: str | None):
    """Exact frame: live adapter grab, session preview, or file decode."""
    if session_id is not None:
        runtime = request.app.state.session_runtimes.get(session_id)
        if runtime is not None and runtime.preview_frames:
            from PIL import Image
            return Image.open(io.BytesIO(runtime.preview_frames[-1])).convert("RGB")
    kind = source_row["type"]
    if kind in LIVE_TYPES:
        return _grab_live_frame(source_row)
    from PIL import Image, ImageOps
    if kind == "media":
        media = store.media.get(source_row["locator"])
        if media is not None:
            return ImageOps.exif_transpose(
                Image.open(media["path"])).convert("RGB")
    else:
        path = Path(source_row["locator"])
        if path.is_file():
            return ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    raise ApiError(503, f"Source {source_row['source_id']!r} produced no frame.")


def _annotation_result(store: Store, observation_id: str | None,
                       session_id: str | None):
    """Build a pseudo-result {task, payload} for the overlay renderer."""
    if observation_id is not None:
        row = store.observations.get(observation_id)
        if row is None:
            raise ApiError(404, f"Unknown observation: {observation_id!r}")
        import json as _json
        body = _json.loads(row["body"])
        return {"task": body.get("task", "detection"),
                "payload": {"items": body.get("items") or []}}
    return None


@router.post("/api/v1/source/{source_id}/capture/", status_code=201)
def post_api_v1_sources_source_id_captures(
    request: Request, store: StoreDep, source_id: str, body: CaptureCreate
) -> JSONResponse:
    require_if_match(request)
    source = _source_or_404(store, source_id)
    if body.session_id is not None and store.sessions.get(body.session_id) is None:
        raise ApiError(404, f"Unknown session: {body.session_id!r}")
    if not source["enabled"]:
        raise ApiError(422, f"Source {source_id!r} is disabled.")
    if body.annotate:
        result = _annotation_result(store, body.observation_id, body.session_id)
        if result is None and body.session_id is None:
            raise ApiError(
                422, "annotate requires observation_id or session_id context.")

    frame = _grab_frame(request, store, source, body.session_id)
    annotated = False
    if body.annotate:
        if result := _annotation_result(store, body.observation_id,
                                        body.session_id):
            frame = annotate(frame, result)
            annotated = True

    capture_id = f"cap-{secrets.token_hex(8)}"
    created = now_iso()
    hours = (effective_settings(store).result_retention_hours if body.retain
             else effective_settings(store).frame_cache_seconds / 3600.0)
    expires = iso(utcnow() + timedelta(hours=max(hours, 1.0 / 3600.0)))
    cap_dir = Path(store.data_dir) / "captures"
    cap_dir.mkdir(parents=True, exist_ok=True)
    path = cap_dir / f"{capture_id}.jpg"
    frame.convert("RGB").save(path, format="JPEG")

    with store.write_txn():
        check_if_match(request, store)
        store.snapshots.insert({
            "snapshot_id": capture_id, "result_id": "",
            "annotated": int(annotated),
            "path": str(path), "width": frame.width, "height": frame.height,
            "created_at": created, "expires_at": expires,
            "source_id": source_id, "session_id": body.session_id,
            "observation_id": body.observation_id,
            "frame_time": created, "mime_type": "image/jpeg",
        })
        revision = store.bump_revision()
    return JSONResponse(capture_read(store.snapshots.get(capture_id)),
                        status_code=201, headers={"ETag": revision})


@router.get("/api/v1/capture/")
def get_api_v1_captures(
    store: StoreDep, source_id: str | None = None,
    limit: int = Query(default=1000, ge=1)
) -> JSONResponse:
    rows = store.snapshots.list_live(now_iso(), source_id)
    return JSONResponse([capture_read(r) for r in rows[:limit]],
                        headers={"ETag": store.config_revision()})


@router.get("/api/v1/capture/{capture_id}")
def get_api_v1_captures_capture_id(store: StoreDep, capture_id: str) -> JSONResponse:
    row = _capture_or_404(store, capture_id)
    if row["expires_at"] <= now_iso():
        raise ApiError(410, f"Capture {capture_id!r} has expired.")
    return JSONResponse(capture_read(row),
                        headers={"ETag": store.config_revision()})


@router.delete("/api/v1/capture/{capture_id}", status_code=204)
def delete_api_v1_captures_capture_id(
    request: Request, response: Response, store: StoreDep, capture_id: str
) -> None:
    require_if_match(request)
    row = _capture_or_404(store, capture_id)
    with store.write_txn():
        check_if_match(request, store)
        store.snapshots.delete(capture_id)
        response.headers["ETag"] = store.bump_revision()
    Path(row["path"]).unlink(missing_ok=True)


@router.get("/api/v1/capture/{capture_id}/content")
def get_api_v1_captures_capture_id_content(store: StoreDep, capture_id: str):
    row = _capture_or_404(store, capture_id)
    if row["expires_at"] <= now_iso():
        raise ApiError(410, f"Capture {capture_id!r} has expired.")
    path = Path(row["path"])
    if not path.is_file():
        raise ApiError(410, f"Capture {capture_id!r} content is gone.")
    mime = row["mime_type"] if "mime_type" in row.keys() and row["mime_type"] \
        else "image/jpeg"
    return FileResponse(path, media_type=mime)

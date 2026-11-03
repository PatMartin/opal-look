"""Synchronous analysis pipeline: selection resolution -> frame acquisition
-> inference -> portable filtering -> persistence -> AnalysisResult.

Frames are decoded orientation-corrected originals; coordinates stay
normalized against them. Filters are portable (applied post-inference);
engine_options are adapter-scoped.
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import time
import zlib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from .engines import ENGINE_REGISTRY, EngineUnavailable, model_runtime
from .errors import ApiError
from .media import is_expired as media_is_expired
from .profiles import profile_errors
from .schemas import AnalyzeRequest, MediaFrameInput, SourceFrameInput
from .settings import effective_settings
from .sources import probe as probe_source
from .store import Store
from .timeutil import iso, now_iso, parse_iso


@dataclass
class Selection:
    profile_id: int | None
    model_id: str
    engine_id: str
    task: str
    settings: dict[str, Any]
    model_row: Any


@dataclass
class Frame:
    image: Any  # PIL.Image oriented RGB
    source_id: str | None
    media_id: str | None
    position_ms: int | None


def resolve_selection(store: Store, req: AnalyzeRequest) -> Selection:
    """explicit profile -> active profile -> request overrides -> defaults."""
    supplied = req.settings.model_dump(exclude_unset=True) if req.settings else {}
    profile_row = None
    if req.profile_id is not None:
        profile_row = store.profiles.get(req.profile_id)
        if profile_row is None:
            raise ApiError(404, f"Unknown profile: {req.profile_id}")
    elif req.model_id is None and req.task is None:
        profile_row = store.profiles.get_active()

    base_model = profile_row["model_id"] if profile_row else None
    base_task = profile_row["task"] if profile_row else None
    base_settings = json.loads(profile_row["settings"]) if profile_row else {}

    model_id = req.model_id or base_model
    task = req.task or base_task
    if model_id is None or task is None:
        raise ApiError(
            422,
            "model_id and task are required when no profile resolves the request.",
        )

    settings = dict(base_settings)
    settings.update({k: v for k, v in supplied.items() if k != "engine_options"})
    settings["engine_options"] = {
        **(base_settings.get("engine_options") or {}),
        **(supplied.get("engine_options") or {}),
    }

    model_row = store.models.get(model_id)
    if model_row is None:
        raise ApiError(404, f"Unknown model: {model_id!r}")
    errors, _ = profile_errors(store, model_row, task, supplied, settings)
    if errors:
        raise ApiError(422, "Request is incompatible with the selected model.", details=errors)
    if settings.get("tracking"):
        raise ApiError(422, "Tracking is not supported for single-frame analysis.")

    read = model_runtime(store, model_row)
    if not read["enabled"]:
        raise ApiError(422, f"Model {model_id!r} is disabled.")
    engine_row = store.engines.get(read["engine_id"])
    if engine_row is None or not read["available"]:
        raise ApiError(503, f"Engine {read['engine_id']!r} is unavailable.")

    return Selection(
        profile_id=profile_row["profile_id"] if profile_row else None,
        model_id=model_id,
        engine_id=read["engine_id"],
        task=task,
        settings=settings,
        model_row=model_row,
    )


def acquire_frame(store: Store, frame_input, max_pixels: int) -> Frame:
    from PIL import Image, ImageOps

    if isinstance(frame_input, MediaFrameInput):
        row = store.media.get(frame_input.media_id)
        if row is None:
            raise ApiError(404, f"Unknown media: {frame_input.media_id!r}")
        if media_is_expired(row):
            raise ApiError(410, f"Media {frame_input.media_id!r} has expired.", code="gone")
        media_id, source_id, position = row["media_id"], None, None
        path = Path(row["path"])
    else:
        row = store.sources.get(frame_input.source_id)
        if row is None:
            raise ApiError(404, f"Unknown source: {frame_input.source_id!r}")
        if frame_input.position_ms and row["type"] not in ("host_video", "media"):
            raise ApiError(422, "position_ms applies only to finite video sources.")
        probed = probe_source(store, row)
        if not row["enabled"] or not probed["available"]:
            raise ApiError(503, f"Source {frame_input.source_id!r} is unavailable.")
        if row["type"] == "media":
            media_row = store.media.get(row["locator"])
            if media_row is None or media_is_expired(media_row):
                raise ApiError(503, f"Source {frame_input.source_id!r} is unavailable.")
            media_id, source_id = row["locator"], row["source_id"]
            path = Path(media_row["path"])
            position = frame_input.position_ms or None
            if position:
                raise ApiError(422, "position_ms is beyond end of media.")
        else:
            image = _grab_live_frame(row)
            if image.width * image.height > max_pixels:
                raise ApiError(413, "Decoded image exceeds the configured pixel limit.")
            return Frame(
                image=image, source_id=row["source_id"], media_id=None,
                position_ms=None)

    try:
        data = path.read_bytes()
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except FileNotFoundError:
        raise ApiError(503, "Media bytes are missing from storage.")
    except Exception:
        raise ApiError(422, "Media bytes could not be decoded.")
    if image.width * image.height > max_pixels:
        raise ApiError(413, "Decoded image exceeds the configured pixel limit.")
    return Frame(image=image, source_id=source_id, media_id=media_id, position_ms=position)


def _grab_live_frame(row) -> Any:
    """One frame from a live source via its capture adapter."""
    from .capture import CaptureError, capture_adapter_for, credentialed_locator

    adapter = capture_adapter_for(row["type"])
    if adapter is None:
        raise ApiError(503, f"Source {row['source_id']!r} is unavailable.")
    options = row["source_options"]
    if isinstance(options, str):
        options = json.loads(options)
    try:
        url = credentialed_locator(row["locator"], row["credential_ref"])
        return adapter.grab(row["locator"], options, url)
    except CaptureError as exc:
        raise ApiError(503, f"Source {row['source_id']!r} is unavailable: {exc}")


def _point_in_polygon(x: float, y: float, polygon: list[dict]) -> bool:
    inside = False
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        if (a["y"] > y) != (b["y"] > y):
            x_cross = (b["x"] - a["x"]) * (y - a["y"]) / (b["y"] - a["y"]) + a["x"]
            if x < x_cross:
                inside = not inside
    return inside


def _in_regions(x: float, y: float, regions: list[dict]) -> bool:
    if not regions:
        return True
    return any(_point_in_polygon(x, y, r["polygon"]) for r in regions)


def _box_center(box: dict) -> tuple[float, float]:
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def apply_filters(payload: dict, task: str, settings: dict) -> dict:
    confidence = settings.get("confidence", 0.25)
    labels = set(settings.get("class_labels") or [])
    regions = settings.get("regions") or []

    def keep(score: float, label: str | None, box: dict | None) -> bool:
        if score < confidence:
            return False
        if labels and label not in labels:
            return False
        if regions and box is not None and not _in_regions(*_box_center(box), regions):
            return False
        return True

    if task == "detection":
        payload["objects"] = [
            o for o in payload["objects"] if keep(o["confidence"], o["label"], o["box"])
        ]
    elif task == "classification":
        payload["classes"] = [
            c for c in payload["classes"] if keep(c["confidence"], c["label"], None)
        ]
    elif task == "pose":
        payload["poses"] = [
            p for p in payload["poses"] if keep(p["confidence"], p["label"], p["box"])
        ]
    elif task == "ocr":
        kept = []
        for r in payload["regions"]:
            if not keep(r["confidence"], None, None):
                continue
            cx = sum(p["x"] for p in r["polygon"]) / len(r["polygon"])
            cy = sum(p["y"] for p in r["polygon"]) / len(r["polygon"])
            if _in_regions(cx, cy, regions):
                kept.append(r)
        payload["regions"] = kept
    elif task == "segmentation":
        if payload.get("kind") == "instance":
            payload["instances"] = [
                i for i in payload["instances"]
                if keep(i["confidence"], i["label"], i["box"])
            ]
        elif regions:
            # Outside-region pixels are unclassified for the synthetic adapter.
            total = payload["map"]["width"] * payload["map"]["height"]
            payload["map"] = {
                "width": payload["map"]["width"],
                "height": payload["map"]["height"],
                "encoding": "rle",
                "runs": [{"class_id": None, "count": total}],
                "classes": [],
            }
    return payload


async def run_analysis(store: Store, req: AnalyzeRequest, frame_cache=None) -> dict[str, Any]:
    app_settings = effective_settings(store)
    if req.pipeline_id is not None:
        return await _run_pipeline_analysis(store, req, app_settings)
    sel = resolve_selection(store, req)
    frame = await asyncio.to_thread(
        acquire_frame, store, req.input, app_settings.max_image_pixels)
    captured_at = now_iso()

    adapter = ENGINE_REGISTRY.get(sel.engine_id)
    desc = model_runtime(store, sel.model_row)
    options = dict(sel.settings.get("engine_options") or {})
    if sel.task == "segmentation":
        options["segmentation_kind"] = sel.settings.get("segmentation_kind", "instance")
    thumb = frame.image.crop((0, 0, min(32, frame.image.width), min(32, frame.image.height)))
    frame_key = zlib.crc32(thumb.tobytes())

    started = time.monotonic()
    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(
                adapter.infer,
                frame.image.width,
                frame.image.height,
                sel.task,
                desc,
                options,
                frame_key,
            ),
            timeout=app_settings.max_analysis_timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise ApiError(504, "Analysis exceeded the configured timeout.", code="analysis_timeout")
    except EngineUnavailable as exc:
        raise ApiError(503, f"Engine {sel.engine_id!r} is unavailable: {exc}")

    payload = apply_filters(payload, sel.task, sel.settings)
    duration_ms = round((time.monotonic() - started) * 1000, 3)
    analyzed_at = now_iso()

    result_id = f"result-{secrets.token_hex(8)}"
    stored = bool(req.store_result)
    expires_at = (
        iso(parse_iso(analyzed_at) + timedelta(hours=app_settings.result_retention_hours))
        if stored
        else None
    )

    result = {
        "result_id": result_id,
        "session_id": None,
        "source_id": frame.source_id,
        "media_id": frame.media_id,
        "model_id": sel.model_id,
        "engine_id": sel.engine_id,
        "task": sel.task,
        "frame_index": 0,
        "tracking_epoch": 0,
        "captured_at": captured_at,
        "analyzed_at": analyzed_at,
        "position_ms": frame.position_ms,
        "width": frame.image.width,
        "height": frame.image.height,
        "duration_ms": duration_ms,
        "stored": stored,
        "expires_at": expires_at,
        "payload": payload,
        "engine_metadata": {"adapter": "synthetic"},
    }

    if stored:
        with store.write_txn():
            store.results.insert(
                {
                    **{k: result[k] for k in (
                        "result_id", "session_id", "source_id", "media_id", "model_id",
                        "engine_id", "task", "frame_index", "tracking_epoch",
                        "captured_at", "analyzed_at", "position_ms", "width",
                        "height", "duration_ms", "expires_at",
                    )},
                    "profile_id": sel.profile_id,
                    "stored": 1,
                    "payload": json.dumps(payload),
                    "engine_metadata": json.dumps(result["engine_metadata"]),
                    "settings": json.dumps(sel.settings),
                }
            )
    if frame_cache is not None:
        frame_cache.put(
            result_id, frame.image, result, app_settings.frame_cache_seconds
        )
    return result


async def _run_pipeline_analysis(store: Store, req: AnalyzeRequest, app_settings) -> dict[str, Any]:
    """v1.5 path: stored pipeline -> DAG executor -> observations."""
    from .correlation import current_ids
    from .pipeline_exec import run_pipeline

    row = store.pipelines.get(req.pipeline_id)
    if row is None:
        raise ApiError(404, f"Unknown pipeline: {req.pipeline_id!r}")
    frame = await asyncio.to_thread(
        acquire_frame, store, req.input, app_settings.max_image_pixels)
    ids = current_ids()
    result = await asyncio.to_thread(
        run_pipeline, store, row, frame.image,
        source_id=frame.source_id, media_id=frame.media_id,
        frame_index=0, transaction_id=ids.transaction_id,
        request_id=ids.request_id, motion_states=None)
    return {
        "observations": result["observations"],
        "processing_ms": result["processing_ms"],
        "media_id": None,
        "_trace": result["trace"],
        "warnings": result["warnings"],
    }

"""Session admission, runtime registry, state machine and worker loop."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
import zlib
from dataclasses import dataclass, field
from typing import Any

from .capture import (
    CaptureError,
    CredentialUnavailable,
    StreamEnded,
    StreamError,
)
from .engines import ENGINE_REGISTRY, EngineUnavailable, model_runtime
from .errors import ApiError
from .media import is_expired as media_is_expired
from .results import result_read
from .schemas import SessionCreate
from .settings import effective_settings
from .sources import LIVE_TYPES, probe as probe_source
from .timeutil import iso, now_iso, expired, utcnow
from datetime import timedelta
from pathlib import Path
import io

TERMINAL = ("stopped", "completed", "failed")


def session_read(row) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "source_id": row["source_id"],
        "profile_id": row["profile_id"],
        "model_id": row["model_id"],
        "engine_id": row["engine_id"],
        "task": row["task"],
        "settings": json.loads(row["settings"]),
        "reconnect": json.loads(row["reconnect"]) if row["reconnect"] else None,
        "store_results": bool(row["store_results"]),
        "state": row["state"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "start_position_ms": row["start_position_ms"],
        "end_position_ms": row["end_position_ms"],
        "frames_analyzed": row["frames_analyzed"],
        "frames_dropped": row["frames_dropped"],
        "tracking_epoch": row["tracking_epoch"],
        "last_result_id": row["last_result_id"],
        "error": json.loads(row["error"]) if row["error"] else None,
    }


@dataclass
class SessionRuntime:
    stop_requested: bool = False
    task_handle: asyncio.Task | None = None
    latest_result: dict | None = None
    events: list = field(default_factory=list)  # [(event_id, kind, payload)]
    preview_frames: list = field(default_factory=list)  # [jpeg bytes]
    updated: asyncio.Event = field(default_factory=asyncio.Event)


class SessionRuntimeRegistry:
    def __init__(self) -> None:
        self._runtimes: dict[str, SessionRuntime] = {}

    def get(self, session_id: str) -> SessionRuntime | None:
        return self._runtimes.get(session_id)

    def ensure(self, session_id: str) -> SessionRuntime:
        return self._runtimes.setdefault(session_id, SessionRuntime())


def _reconnect_policy(store, session_id: str) -> dict[str, Any]:
    """Effective reconnect policy for a live session (contract defaults)."""
    row = store.sessions.get(session_id)
    stored = json.loads(row["reconnect"]) if row is not None and row["reconnect"] else None
    return stored or {
        "enabled": True,
        "max_attempts": 10,
        "initial_delay_ms": 1000,
        "max_delay_ms": 30000,
    }


def _fail(store, session_id: str, code: str, message: str) -> None:
    store.sessions.update(session_id, {
        "state": "failed", "finished_at": now_iso(),
        "error": {"code": code, "message": message},
    })


async def _worker(app, store, session_id: str, sel, source_row, store_results: bool) -> None:
    runtime = app.state.session_runtimes.ensure(session_id)
    adapter = ENGINE_REGISTRY.get(sel.engine_id)
    desc = model_runtime(store, sel.model_row)
    store.sessions.update(session_id, {"state": "running", "started_at": now_iso()})
    _state_event(app, store, runtime, session_id, "running")
    frame_index = 0
    dropped_total = 0
    tracking_epoch = 0
    live = source_row["type"] in LIVE_TYPES
    max_fps = sel.settings.get("max_fps") or 5
    last_analysis = 0.0
    policy = _reconnect_policy(store, session_id) if live else None
    attempts = 0
    reconnecting = False
    try:
        while True:
            try:
                gen = _frames(store, source_row)
                try:
                    async for produced in gen:
                        if runtime.stop_requested:
                            store.sessions.update(
                                session_id, {"state": "stopped", "finished_at": now_iso()})
                            return
                        if live:
                            wait = (1.0 / max_fps) - (time.monotonic() - last_analysis)
                            if wait > 0:
                                await asyncio.sleep(wait)
                        frame = produced.image
                        dropped_total += produced.dropped
                        captured = now_iso()
                        last_analysis = time.monotonic()
                        if reconnecting:
                            reconnecting = False
                            store.sessions.update(session_id, {"state": "running"})
                            _state_event(app, store, runtime, session_id, "running")
                        thumb = frame.crop((0, 0, min(32, frame.width), min(32, frame.height)))
                        payload = await asyncio.to_thread(
                            adapter.infer, frame.width, frame.height, sel.task, desc,
                            sel.settings.get("engine_options") or {}, zlib.crc32(thumb.tobytes()))
                        from .analysis import apply_filters
                        payload = apply_filters(payload, sel.task, sel.settings)
                        rid = f"result-{secrets.token_hex(8)}"
                        analyzed = now_iso()
                        expires = iso(utcnow() + timedelta(
                            hours=effective_settings(store).result_retention_hours)) if store_results else None
                        media_id = source_row["locator"] if source_row["type"] == "media" else None
                        result = {
                            "result_id": rid, "session_id": session_id, "source_id": source_row["source_id"],
                            "media_id": media_id, "model_id": sel.model_id, "engine_id": sel.engine_id,
                            "task": sel.task, "frame_index": frame_index,
                            "tracking_epoch": tracking_epoch,
                            "captured_at": captured, "analyzed_at": analyzed,
                            "position_ms": None, "width": frame.width, "height": frame.height,
                            "duration_ms": 0.0, "stored": bool(store_results), "expires_at": expires,
                            "payload": payload, "engine_metadata": {"adapter": "synthetic"},
                        }
                        if store_results:
                            with store.write_txn():
                                store.results.insert({**{k: result[k] for k in (
                                    "result_id", "session_id", "source_id", "media_id", "model_id",
                                    "engine_id", "task", "frame_index", "tracking_epoch", "captured_at",
                                    "analyzed_at", "position_ms", "width", "height", "duration_ms",
                                    "expires_at")}, "profile_id": sel.profile_id, "stored": 1,
                                    "payload": json.dumps(payload),
                                    "engine_metadata": json.dumps(result["engine_metadata"]),
                                    "settings": json.dumps(sel.settings)})
                        runtime.latest_result = result
                        app.state.frame_cache.put(
                            rid, frame.copy(), result, effective_settings(store).frame_cache_seconds)
                        buf = io.BytesIO()
                        frame.convert("RGB").save(buf, format="JPEG")
                        runtime.preview_frames.append(buf.getvalue())
                        runtime.events.append((frame_index, "result", result))
                        runtime.updated.set()
                        runtime.updated = asyncio.Event()
                        try:
                            from .events import publish_event
                            publish_event(app, store, "opal.look.result", session_id, result)
                        except Exception:
                            pass
                        # Reset attempts after the first successfully analyzed
                        # frame following reconnection.
                        attempts = 0
                        frame_index += 1
                        store.sessions.update(session_id, {
                            "frames_analyzed": frame_index, "frames_dropped": dropped_total,
                            "tracking_epoch": tracking_epoch, "last_result_id": rid})
                finally:
                    await gen.aclose()
                store.sessions.update(session_id, {"state": "completed", "finished_at": now_iso()})
                return
            except CredentialUnavailable:
                raise
            except (StreamError, StreamEnded, CaptureError) as exc:
                if policy is None or not policy.get("enabled", True) or attempts >= policy["max_attempts"]:
                    _fail(store, session_id, "source_disconnected",
                          str(exc) or type(exc).__name__)
                    return
                attempts += 1
                tracking_epoch += 1
                reconnecting = True
                store.sessions.update(session_id, {
                    "state": "reconnecting", "tracking_epoch": tracking_epoch})
                _state_event(app, store, runtime, session_id, "reconnecting")
                delay_ms = min(
                    policy["initial_delay_ms"] * (2 ** (attempts - 1)),
                    policy["max_delay_ms"])
                await asyncio.sleep(delay_ms / 1000)
    except asyncio.CancelledError:
        store.sessions.update(session_id, {"state": "stopped", "finished_at": now_iso()})
        raise
    except Exception as exc:  # source/inference failure -> failed
        _fail(store, session_id, "session_failed", str(exc) or type(exc).__name__)
    finally:
        row = store.sessions.get(session_id)
        if row is not None and row["state"] in TERMINAL:
            _state_event(app, store, runtime, session_id, row["state"])
            runtime.events.append((frame_index + 10_000, "end", {"state": row["state"]}))
            runtime.updated.set()


def _state_event(app, store, runtime, session_id: str, state: str) -> None:
    runtime.events.append((len(runtime.events), "state", {"state": state}))
    runtime.updated.set()
    try:
        from .events import publish_event
        publish_event(app, store, "opal.look.session.state", session_id, {"state": state})
    except Exception:
        pass


@dataclass
class ProducedFrame:
    image: Any
    dropped: int = 0


async def _frames(store, source_row):
    """Async generator of ProducedFrame for a session source."""
    from PIL import Image, ImageOps

    if source_row["type"] == "media":
        media = store.media.get(source_row["locator"])
        if media is None or media_is_expired(media):
            raise ApiError(503, "source media unavailable")
        data = Path(media["path"]).read_bytes()
        yield ProducedFrame(
            ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB"))
        return
    if source_row["type"] in LIVE_TYPES:
        inner = _live_frames(source_row)
        try:
            async for produced in inner:
                yield produced
        finally:
            await inner.aclose()
        return
    raise ApiError(503, "no frame producer for this source type")
    yield  # pragma: no cover


async def _live_frames(source_row):
    """ProducedFrames from a capture adapter via a drop-oldest pump.

    Live sources prioritize fresh frames: the pump keeps only the latest
    decoded frame; evicted frames accumulate into ``dropped``. Stream
    failures surface as StreamError/StreamEnded (handled by the worker).
    """
    from .capture import (
        CaptureError,
        LiveFramePump,
        capture_adapter_for,
        credentialed_locator,
    )

    adapter = capture_adapter_for(source_row["type"])
    if adapter is None:
        raise CaptureError(f"no capture adapter for {source_row['type']!r}")
    options = source_row["source_options"]
    if isinstance(options, str):
        options = json.loads(options)
    url = await asyncio.to_thread(
        credentialed_locator, source_row["locator"], source_row["credential_ref"])
    stream = await asyncio.to_thread(
        adapter.open_stream, source_row["locator"], options, url)
    pump = LiveFramePump(stream).start()
    try:
        while True:
            image = await asyncio.to_thread(pump.get)
            yield ProducedFrame(image, pump.take_dropped())
    finally:
        pump.close()

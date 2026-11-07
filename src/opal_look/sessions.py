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
    """Contract Session shape (upstream v1.5)."""
    error = json.loads(row["error"]) if row["error"] else None
    cols = row.keys()
    return {
        "id": row["session_id"],
        "state": row["state"],
        "source_id": row["source_id"],
        "pipeline_id": row["pipeline_id"] if "pipeline_id" in cols else None,
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "ended_at": row["finished_at"],
        "processed_frames": row["frames_analyzed"],
        "dropped_frames": row["frames_dropped"],
        "last_observation_at": (
            row["last_observation_at"] if "last_observation_at" in cols else None),
        "failure": error,
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


async def _pipeline_worker(app, store, session_id: str, pipeline_row,
                           source_row, options: dict, retention: dict) -> None:
    """Upstream session worker: run the pipeline over the source's frames.

    Emits observations (persisted when retention.persist_results), SSE events
    and MJPEG preview frames through the session runtime. State machine:
    starting -> running -> stopping/stopped|completed|failed.
    """
    from .pipeline_exec import run_pipeline

    runtime = app.state.session_runtimes.ensure(session_id)
    store.sessions.update(session_id, {"state": "running",
                                       "started_at": now_iso()})
    _state_event(app, store, runtime, session_id, "running")
    live = source_row["type"] in LIVE_TYPES
    target_fps = (options.get("target_fps") or 5) if live else 0
    max_frames = options.get("max_frames")
    frame_index = 0
    dropped_total = 0
    last_analysis = 0.0
    policy = _reconnect_policy(store, session_id) if live else None
    attempts = 0
    persist = bool(retention.get("persist_results"))
    ttl = retention.get("ttl_seconds")
    try:
        while True:
            try:
                gen = _frames(store, source_row)
                try:
                    async for produced in gen:
                        if runtime.stop_requested:
                            store.sessions.update(
                                session_id, {"state": "stopped",
                                             "finished_at": now_iso()})
                            return
                        if max_frames is not None and frame_index >= max_frames:
                            store.sessions.update(
                                session_id, {"state": "completed",
                                             "finished_at": now_iso()})
                            return
                        if target_fps:
                            wait = (1.0 / target_fps) - (
                                time.monotonic() - last_analysis)
                            if wait > 0:
                                await asyncio.sleep(wait)
                        frame = produced.image
                        dropped_total += produced.dropped
                        last_analysis = time.monotonic()
                        result = await asyncio.to_thread(
                            run_pipeline, store, pipeline_row, frame,
                            source_id=source_row["source_id"], media_id=None,
                            frame_index=frame_index,
                            transaction_id=session_id, request_id=session_id)
                        attempts = 0
                        frame_index += 1
                        now = now_iso()
                        obs_list = result.get("observations") or []
                        for obs in obs_list:
                            obs["session_id"] = session_id
                        runtime.latest_result = result
                        buf = io.BytesIO()
                        (result.get("presentation", {}).get("image")
                         or frame).convert("RGB").save(buf, format="JPEG")
                        runtime.preview_frames.append(buf.getvalue())
                        del runtime.preview_frames[:-8]
                        for obs in obs_list:
                            runtime.events.append(
                                (frame_index, "observation", obs))
                        runtime.updated.set()
                        runtime.updated = asyncio.Event()
                        expires = None
                        if persist:
                            if ttl:
                                expires = iso(utcnow() + timedelta(seconds=ttl))
                            else:
                                expires = iso(utcnow() + timedelta(
                                    hours=effective_settings(
                                        store).result_retention_hours))
                            with store.write_txn():
                                for obs in obs_list:
                                    store.observations.insert(obs, expires)
                        store.sessions.update(session_id, {
                            "frames_analyzed": frame_index,
                            "frames_dropped": dropped_total,
                            "last_observation_at": now,
                        })
                        try:
                            from .events import publish_event
                            for obs in obs_list:
                                publish_event(app, store, "opal.look.observation",
                                              session_id, obs)
                        except Exception:
                            pass
                finally:
                    await gen.aclose()
                store.sessions.update(session_id, {
                    "state": "completed", "finished_at": now_iso()})
                return
            except CredentialUnavailable:
                raise
            except (StreamError, StreamEnded, CaptureError) as exc:
                if (policy is None or not policy.get("enabled", True)
                        or attempts >= policy["max_attempts"]):
                    _fail(store, session_id, "source_disconnected",
                          str(exc) or type(exc).__name__)
                    return
                attempts += 1
                delay_ms = min(
                    policy["initial_delay_ms"] * (2 ** (attempts - 1)),
                    policy["max_delay_ms"])
                await asyncio.sleep(delay_ms / 1000)
    except asyncio.CancelledError:
        store.sessions.update(session_id, {"state": "stopped",
                                           "finished_at": now_iso()})
        raise
    except Exception as exc:  # noqa: BLE001
        _fail(store, session_id, "session_failed",
              str(exc) or type(exc).__name__)
    finally:
        row = store.sessions.get(session_id)
        if row is not None and row["state"] in TERMINAL:
            _state_event(app, store, runtime, session_id, row["state"])
            runtime.events.append(
                (frame_index + 10_000, "end", {"state": row["state"]}))
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

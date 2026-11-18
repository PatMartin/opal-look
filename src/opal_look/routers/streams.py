"""Ephemeral RTSP stream endpoints: lifecycle, video, snapshot, metrics, SSE."""

from __future__ import annotations

import hashlib
import json
import queue
import threading
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..capture import (CredentialUnavailable, capture_adapter_for,
                       resolve_credentials)
from ..dependencies import StoreDep
from ..engines import (EngineRegistry, EngineUnavailable, engine_gate)
from ..errors import ApiError
from ..idempotency import request_idempotency_key
from ..schemas import StreamStartRequest
from ..settings import effective_settings
from ..source_policy import RTSP_SCHEMES, SourcePolicy
from ..streams import TERMINAL_STATES, StreamRuntime
from ..timeutil import now_iso, plus_hours, iso

router = APIRouter()

_HEARTBEAT_SECONDS = 15.0
_ADMISSION_LOCK = threading.Lock()


def _runtimes(request: Request) -> dict[str, StreamRuntime]:
    return request.app.state.stream_runtimes


def _get_or_404(request: Request, stream_id: str) -> StreamRuntime:
    """Resolve a run id exactly, else a client-chosen name as an alias.

    Run ids always win; a name resolves only its current non-terminal
    holder, so a terminal stream releases the alias (the run stays
    addressable by its run id)."""
    rt = _runtimes(request).get(stream_id)
    if rt is None:
        rt = next((r for r in _runtimes(request).values()
                   if r.name == stream_id
                   and r.status not in TERMINAL_STATES), None)
    if rt is None:
        raise ApiError(404, f"Unknown stream: {stream_id!r}")
    return rt


def _fingerprint(body: StreamStartRequest) -> str:
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _admit_engine(store, body: StreamStartRequest,
                  registry: EngineRegistry):
    """Resolve and gate the inference engine; returns adapter or None."""
    if body.engine_id is None:
        return None
    adapter = registry.get(body.engine_id)
    if adapter is None:
        raise ApiError(404, f"Unknown engine: {body.engine_id!r}")
    engine_gate(store, adapter)
    try:
        model = next((m for m in adapter.models()
                      if m["model_id"] == body.model_id), None)
        devices = adapter.hardware()
        errors = adapter.validate_engine_options(
            body.engine_options or {})
        supports_annotate = bool(
            adapter.capabilities().get("annotation"))
    except EngineUnavailable as exc:
        raise ApiError(503, str(exc))
    if model is None:
        raise ApiError(404, f"Unknown model: {body.model_id!r}")
    if not model.get("loaded"):
        raise ApiError(409, f"Model {body.model_id!r} is not loaded.")
    if body.device_id is not None and not any(
            d["device_id"] == body.device_id for d in devices):
        raise ApiError(422, f"Unknown device: {body.device_id!r}")
    if errors:
        raise ApiError(422, "Invalid engine options.", details=errors)
    if body.annotate and not supports_annotate:
        raise ApiError(422, f"Engine {body.engine_id!r} does not support "
                            "annotation.")
    return adapter


@router.post("/api/v1/stream/")
def post_api_v1_stream(request: Request, store: StoreDep,
                       body: StreamStartRequest) -> JSONResponse:
    key = request_idempotency_key(request)
    fingerprint = _fingerprint(body)

    limits = effective_settings(store)
    SourcePolicy.from_settings(limits).check_network(
        body.source, RTSP_SCHEMES, "Stream")
    runtimes = _runtimes(request)
    adapter = _admit_engine(store, body,
                            request.app.state.engine_registry)
    if capture_adapter_for("rtsp") is None:
        raise ApiError(503, "No RTSP capture backend is installed.")
    try:
        resolve_credentials(body.credential_ref)
    except CredentialUnavailable as exc:
        raise ApiError(422, str(exc)) from exc

    # Check-and-mutate under one lock: key lookup, fingerprint validation,
    # admission limit, name conflict, runtime insert, and the durable
    # receipt binding are atomic with respect to concurrent admissions.
    with _ADMISSION_LOCK:
        if key:
            row = store._conn.execute(
                "SELECT fingerprint, session_id FROM idempotency_keys "
                "WHERE key = ? AND expires_at > ?",
                (key, now_iso())).fetchone()
            if row is not None:
                if row["fingerprint"] != fingerprint:
                    raise ApiError(409, "Idempotency-Key was used with a "
                                        "different request body.")
                bound = runtimes.get(row["session_id"])
                if bound is not None:
                    # Fingerprint replay returns the recorded run's receipt —
                    # never a different run that reused the name.
                    return JSONResponse(
                        bound.status_dict(), status_code=202,
                        headers={"Location":
                                 f"/api/v1/stream/{bound.stream_id}"})
                # The binding outlived its run (process restart — runtimes
                # are ephemeral): re-admit and rebind the key below.
        active = sum(1 for rt in runtimes.values()
                     if rt.status not in TERMINAL_STATES)
        if active >= limits.max_concurrent_streams:
            raise ApiError(429, "Stream admission limit reached "
                                f"({limits.max_concurrent_streams}).")
        if body.name is not None:
            holder = next((r for r in runtimes.values()
                           if r.name == body.name
                           and r.status not in TERMINAL_STATES), None)
            if holder is not None:
                raise ApiError(409, f"Stream name {body.name!r} is "
                                    "already in use.")
        rt = StreamRuntime(
            name=body.name,
            source=body.source, credential_ref=body.credential_ref,
            engine=adapter, model_id=body.model_id,
            confidence=body.confidence, device_id=body.device_id,
            engine_options=body.engine_options, annotate=body.annotate,
            buffer_policy=body.buffer_policy, buffer_size=body.buffer_size,
            sse_buffer=limits.sse_buffer_events,
            max_viewers=limits.max_viewers)
        if key:
            with store.write_txn():
                store._conn.execute(
                    "INSERT OR REPLACE INTO idempotency_keys "
                    "(key, fingerprint, session_id, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (key, fingerprint, rt.stream_id, now_iso(),
                     iso(plus_hours(24))))
        runtimes[rt.stream_id] = rt
    rt.start()
    return JSONResponse(rt.status_dict(), status_code=202,
                        headers={"Location":
                                 f"/api/v1/stream/{rt.stream_id}"})


@router.get("/api/v1/stream/")
def get_api_v1_streams(request: Request) -> JSONResponse:
    return JSONResponse([
        rt.status_dict() for rt in _runtimes(request).values()
        if rt.status not in TERMINAL_STATES
    ])


@router.get("/api/v1/stream/{stream_id}")
def get_api_v1_stream(request: Request, stream_id: str) -> JSONResponse:
    return JSONResponse(_get_or_404(request, stream_id).status_dict())


@router.post("/api/v1/stream/{stream_id}/stop")
def post_api_v1_stream_stop(request: Request,
                            stream_id: str) -> JSONResponse:
    rt = _get_or_404(request, stream_id)
    if rt.status in TERMINAL_STATES or rt.status == "stopping":
        raise ApiError(409, f"Stream {stream_id!r} is already "
                            f"{rt.status}.")
    rt.stop()
    return JSONResponse(rt.status_dict())


def _check_annotated(rt: StreamRuntime, annotated: bool) -> None:
    if not annotated:
        return
    if rt.mode != "inference" or not rt.annotate:
        raise ApiError(422, "Annotated output is only available in inference "
                            "streams started with annotate=true.")


@router.get("/api/v1/stream/{stream_id}/events")
def get_api_v1_stream_events(request: Request,
                             stream_id: str) -> StreamingResponse:
    rt = _get_or_404(request, stream_id)
    raw = request.headers.get("last-event-id")
    last_id: int | None = None
    if raw is not None:
        if not raw.isdigit():
            raise ApiError(422, "Invalid Last-Event-ID header.")
        last_id = int(raw)
    try:
        sub = rt.subscribe(last_id)
    except ValueError:
        raise ApiError(409, "Last-Event-ID is outside the replay window.")

    def gen():
        try:
            while True:
                try:
                    seq, etype, data = sub.get(timeout=_HEARTBEAT_SECONDS)
                except queue.Empty:
                    yield ": heartbeat\n\n"
                    continue
                yield (f"id: {seq}\nevent: {etype}\n"
                       f"data: {json.dumps(data)}\n\n")
                if etype in ("terminal", "dropped"):
                    break
        finally:
            rt.unsubscribe(sub)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/api/v1/stream/{stream_id}/video")
def get_api_v1_stream_video(request: Request, stream_id: str,
                            annotated: bool = False) -> StreamingResponse:
    rt = _get_or_404(request, stream_id)
    _check_annotated(rt, annotated)
    if rt.status in TERMINAL_STATES:
        raise ApiError(409, f"Stream {stream_id!r} is {rt.status}.")
    # Subscribe before the response starts so the viewer cap answers 429.
    sub = rt.subscribe(None)

    def gen():
        try:
            jpg = rt.latest_jpeg(annotated)
            if jpg is not None:
                yield _mjpeg_part(jpg)
            while True:
                try:
                    seq, etype, data = sub.get(timeout=_HEARTBEAT_SECONDS)
                except queue.Empty:
                    continue
                if etype in ("terminal", "dropped"):
                    break
                if etype != "frame":
                    continue
                jpg = rt.latest_jpeg(annotated)
                if jpg is not None:
                    yield _mjpeg_part(jpg)
        finally:
            rt.unsubscribe(sub)

    return StreamingResponse(
        gen(),
        media_type="multipart/x-mixed-replace; boundary=opalframe")


def _mjpeg_part(jpeg: bytes) -> bytes:
    return (b"--opalframe\r\nContent-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(jpeg)).encode()
            + b"\r\n\r\n" + jpeg + b"\r\n")


@router.get("/api/v1/stream/{stream_id}/snapshot")
def get_api_v1_stream_snapshot(request: Request, stream_id: str,
                               annotated: bool = False) -> Response:
    rt = _get_or_404(request, stream_id)
    _check_annotated(rt, annotated)
    if rt.status in TERMINAL_STATES:
        raise ApiError(409, f"Stream {stream_id!r} is {rt.status}.")
    jpg = rt.latest_jpeg(annotated)
    if jpg is None:
        raise ApiError(404, "No frame is available yet.")
    return Response(jpg, media_type="image/jpeg")


@router.get("/api/v1/stream/{stream_id}/metrics")
def get_api_v1_stream_metrics(request: Request,
                              stream_id: str) -> JSONResponse:
    rt = _get_or_404(request, stream_id)
    return JSONResponse(rt.metrics_dict())

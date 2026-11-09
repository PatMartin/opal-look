"""Session endpoints (upstream): start/list/show/stop/observations/stream/preview."""

from __future__ import annotations

import asyncio
import json
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..idempotency import request_idempotency_key
from ..schemas import SessionCreate
from ..sessions import _pipeline_worker, session_read
from ..settings import effective_settings
from ..sources import LIVE_TYPES, probe
from ..store import Store
from ..timeutil import now_iso

router = APIRouter()

_TERMINAL = ("stopped", "completed", "failed")


def _session_or_404(store: Store, session_id: str):
    row = store.sessions.get(session_id)
    if row is None:
        raise ApiError(404, f"Unknown session: {session_id!r}")
    return row


def _resolve_pipeline(store: Store, body: SessionCreate) -> tuple:
    """Return (pipeline_row, profile_row|None). Explicit pipeline wins; then
    the profile's pipeline_id; then the default_pipeline_id setting."""
    profile = None
    pipeline_id = body.pipeline_id
    if body.profile_id is not None:
        profile = store.profiles.get(body.profile_id)
        if profile is None:
            raise ApiError(404, f"Unknown profile: {body.profile_id}")
        if pipeline_id is None:
            import json as _json
            pipeline_id = _json.loads(profile["data"] or "{}").get("pipeline_id")
    if pipeline_id is None:
        pipeline_id = effective_settings(store).default_pipeline_id
    if pipeline_id is None:
        raise ApiError(422, "No pipeline_id supplied and no default configured.")
    pipeline = store.pipelines.get(pipeline_id)
    if pipeline is None:
        raise ApiError(404, f"Unknown pipeline: {pipeline_id!r}")
    return pipeline, profile


def _merged_options(body: SessionCreate, profile) -> dict:
    import json as _json
    merged: dict = {}
    if profile is not None:
        merged.update(_json.loads(profile["data"] or "{}").get("inference") or {})
    if body.options is not None:
        merged.update(body.options.model_dump(exclude_unset=True))
    return merged


def _merged_retention(body: SessionCreate, profile) -> dict:
    import json as _json
    merged: dict = {}
    if profile is not None:
        merged.update(_json.loads(profile["data"] or "{}").get("retention") or {})
    if body.retention is not None:
        merged.update(body.retention.model_dump(exclude_unset=True))
    return merged


@router.post("/api/v1/session/", status_code=201)
async def post_api_v1_sessions(request: Request, store: StoreDep, body: SessionCreate):
    idem = request_idempotency_key(request)
    if idem is not None:
        import hashlib
        fingerprint = hashlib.sha256(
            json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        prior = store.sessions.get_idempotency(idem, now_iso())
        if prior is not None:
            if prior["fingerprint"] != fingerprint:
                raise ApiError(409, "Idempotency-Key was used with a different request.",
                               code="idempotency_conflict")
            prior_session = store.sessions.get(prior["session_id"])
            if prior_session is None:
                raise ApiError(409, "The session created by this Idempotency-Key "
                                    "was deleted.", code="idempotency_conflict")
            return JSONResponse(
                session_read(prior_session), status_code=201,
                headers={"Location": f"/api/v1/session/{prior['session_id']}"})

    source = store.sources.get(body.source_id)
    if source is None:
        raise ApiError(404, f"Unknown source: {body.source_id!r}")
    probed = probe(store, source)
    if not source["enabled"] or not probed["available"]:
        raise ApiError(503, f"Source {body.source_id!r} is unavailable.")
    pipeline, profile = _resolve_pipeline(store, body)
    options = _merged_options(body, profile)
    retention = _merged_retention(body, profile)

    settings = effective_settings(store)
    if store.sessions.count_nonterminal() >= settings.max_concurrent_sessions:
        raise ApiError(429, "Session admission capacity exhausted.",
                       code="capacity_exceeded")

    session_id = f"session-{secrets.token_hex(8)}"
    with store.write_txn():
        store.sessions.insert({
            "session_id": session_id, "source_id": body.source_id,
            "profile_id": body.profile_id, "model_id": "", "engine_id": "",
            "task": "", "settings": json.dumps(options),
            "reconnect": None,
            "store_results": 1 if retention.get("persist_results")
                             or retention.get("persist_observations") else 0,
            "state": "starting" if body.auto_start else "queued",
            "created_at": now_iso(),
            "pipeline_id": pipeline["pipeline_id"],
            "options": json.dumps(options),
            "retention": json.dumps(retention),
        })
        if idem is not None:
            store.sessions.put_idempotency(idem, fingerprint, session_id)
    if body.auto_start:
        handle = asyncio.create_task(
            _pipeline_worker(request.app, store, session_id, pipeline,
                             source, options, retention))
        request.app.state.session_runtimes.ensure(session_id).task_handle = handle
    return JSONResponse(
        session_read(store.sessions.get(session_id)),
        status_code=201,
        headers={"Location": f"/api/v1/session/{session_id}"},
    )


@router.get("/api/v1/session/")
def get_api_v1_sessions(request: Request, store: StoreDep) -> JSONResponse:
    rows = store.sessions.page(now_iso(),
                               effective_settings(store).result_retention_hours,
                               {}, None, 1000)
    return JSONResponse([session_read(r) for r in rows],
                        headers={"ETag": store.config_revision()})


@router.get("/api/v1/session/{session_id}")
def get_api_v1_sessions_session_id(store: StoreDep, session_id: str) -> JSONResponse:
    return JSONResponse(session_read(_session_or_404(store, session_id)),
                        headers={"ETag": store.config_revision()})


@router.post("/api/v1/session/{session_id}/stop")
def post_api_v1_sessions_session_id_stop(
    request: Request, store: StoreDep, session_id: str
) -> JSONResponse:
    row = _session_or_404(store, session_id)
    if row["state"] in _TERMINAL:
        raise ApiError(409, f"Session {session_id!r} is already {row['state']}.",
                       code="invalid_state")
    runtime = request.app.state.session_runtimes.ensure(session_id)
    if row["state"] == "queued":
        # never started: terminalize directly
        store.sessions.update(session_id, {"state": "stopped",
                                           "finished_at": now_iso()})
    else:
        store.sessions.update(session_id, {"state": "stopping"})
        runtime.stop_requested = True
        runtime.updated.set()
    return JSONResponse(session_read(store.sessions.get(session_id)),
                        headers={"ETag": store.config_revision()})


@router.get("/api/v1/session/{session_id}/observation/")
def get_api_v1_sessions_observations(
    store: StoreDep, session_id: str, limit: int = 100
) -> JSONResponse:
    _session_or_404(store, session_id)
    rows = store.observations.page(now_iso(), {"session_id": session_id},
                                   None, min(limit, 500))
    return JSONResponse([json.loads(r["body"]) for r in rows],
                        headers={"ETag": store.config_revision()})


@router.get("/api/v1/session/{session_id}/stream")
async def get_api_v1_sessions_session_id_stream(
    request: Request, store: StoreDep, session_id: str
) -> StreamingResponse:
    _session_or_404(store, session_id)
    runtime = request.app.state.session_runtimes.ensure(session_id)

    async def events():
        sent = 0
        yield ": heartbeat\n\n"
        while True:
            evts = runtime.events[sent:]
            for eid, kind, payload in evts:
                yield (f"id: {eid}\nevent: {kind}\n"
                       f"data: {json.dumps(payload)}\n\n")
            sent = len(runtime.events)
            row = store.sessions.get(session_id)
            if row is not None and row["state"] in _TERMINAL and sent >= len(runtime.events):
                return
            try:
                await asyncio.wait_for(runtime.updated.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/api/v1/session/{session_id}/preview")
async def get_api_v1_sessions_session_id_preview(
    request: Request, store: StoreDep, session_id: str
) -> StreamingResponse:
    _session_or_404(store, session_id)
    runtime = request.app.state.session_runtimes.ensure(session_id)

    async def frames():
        sent = 0
        while True:
            for jpeg in runtime.preview_frames[sent:]:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + jpeg + b"\r\n")
            sent = len(runtime.preview_frames)
            row = store.sessions.get(session_id)
            if row is not None and row["state"] in _TERMINAL \
                    and sent >= len(runtime.preview_frames):
                return
            try:
                await asyncio.wait_for(runtime.updated.wait(), timeout=15)
            except asyncio.TimeoutError:
                continue

    return StreamingResponse(
        frames(), media_type="multipart/x-mixed-replace; boundary=frame")

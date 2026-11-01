"""Analysis session endpoints: admission, list, get, delete, stop, latest."""

from __future__ import annotations

import asyncio
import re
import secrets

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..analysis import resolve_selection
from ..dependencies import StoreDep
from ..errors import ApiError
from ..pagination import decode_cursor, encode_cursor, filter_key
from ..schemas import SessionCreate
from ..sessions import TERMINAL, _worker, session_read
from ..settings import effective_settings
from ..sources import LIVE_TYPES, probe as probe_source
from ..timeutil import now_iso

router = APIRouter()

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


@router.post("/api/v1/sessions/", status_code=202)
async def post_api_v1_sessions(request: Request, store: StoreDep, body: SessionCreate):
    idem = request.headers.get("idempotency-key")
    if idem is not None and not _IDEMPOTENCY_RE.match(idem):
        raise ApiError(422, "Invalid Idempotency-Key header.")

    source = store.sources.get(body.source_id)
    if source is None:
        raise ApiError(404, f"Unknown source: {body.source_id!r}")
    if body.reconnect is not None and source["type"] not in LIVE_TYPES:
        raise ApiError(422, "reconnect policy applies only to live sources.")
    if source["type"] in LIVE_TYPES and (body.start_position_ms or body.end_position_ms is not None):
        raise ApiError(422, "Position controls apply only to finite media sources.")
    probed = probe_source(store, source)
    if not source["enabled"] or not probed["available"]:
        raise ApiError(503, f"Source {body.source_id!r} is unavailable.")

    sel = resolve_selection(store, body)

    settings = effective_settings(store)
    if store.sessions.count_nonterminal() >= settings.max_concurrent_sessions:
        raise ApiError(429, "Session admission capacity exhausted.", code="capacity_exceeded")

    session_id = f"session-{secrets.token_hex(8)}"
    with store.write_txn():
        store.sessions.insert({
            "session_id": session_id, "source_id": body.source_id,
            "profile_id": sel.profile_id, "model_id": sel.model_id,
            "engine_id": sel.engine_id, "task": sel.task,
            "settings": sel.settings,
            "reconnect": body.reconnect.model_dump() if body.reconnect else None,
            "store_results": body.store_results, "state": "starting",
            "created_at": now_iso(),
            "start_position_ms": body.start_position_ms or None,
            "end_position_ms": body.end_position_ms,
        })
    handle = asyncio.create_task(
        _worker(request.app, store, session_id, sel, source, body.store_results))
    request.app.state.session_runtimes.ensure(session_id).task_handle = handle
    return JSONResponse(
        session_read(store.sessions.get(session_id)),
        status_code=202,
        headers={"Location": f"/api/v1/sessions/{session_id}"},
    )


@router.get("/api/v1/sessions/")
def get_api_v1_sessions(
    request: Request,
    store: StoreDep,
    source_id: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None, min_length=1),
) -> dict:
    if state is not None and state not in (
        "starting", "running", "stopping", "reconnecting", "stopped", "completed", "failed"
    ):
        raise ApiError(422, f"Invalid state filter: {state!r}")
    filters = {"source_id": source_id, "state": state}
    fkey = filter_key({k: v for k, v in filters.items() if v is not None})
    after, _, _ = decode_cursor(cursor, fkey)
    rows = store.sessions.page(
        now_iso(), effective_settings(store).result_retention_hours, filters, after, limit)
    items = rows[:limit]
    has_more = len(rows) > limit
    next_cursor = (
        encode_cursor(fkey, [items[-1]["created_at"], items[-1]["session_id"]])
        if has_more else None
    )
    return {"items": [session_read(r) for r in items], "next_cursor": next_cursor,
            "has_more": has_more}


def _session_or_404(store, session_id: str):
    row = store.sessions.get(session_id)
    if row is None:
        raise ApiError(404, f"Unknown session: {session_id!r}")
    return row


@router.get("/api/v1/sessions/{session_id}")
def get_api_v1_sessions_session_id(request: Request, store: StoreDep, session_id: str) -> dict:
    return session_read(_session_or_404(store, session_id))


@router.delete("/api/v1/sessions/{session_id}", status_code=204)
def delete_api_v1_sessions_session_id(request: Request, store: StoreDep, session_id: str) -> None:
    row = _session_or_404(store, session_id)
    if row["state"] not in TERMINAL:
        raise ApiError(409, "Session must be terminal before deletion.")
    with store.write_txn():
        store.sessions.delete(session_id)


@router.post("/api/v1/sessions/{session_id}/stop")
def post_api_v1_sessions_session_id_stop(request: Request, store: StoreDep, session_id: str) -> dict:
    row = _session_or_404(store, session_id)
    if row["state"] not in TERMINAL:
        runtime = request.app.state.session_runtimes.get(session_id)
        if runtime:
            runtime.stop_requested = True
            if runtime.task_handle:
                runtime.task_handle.cancel()
        with store.write_txn():
            store.sessions.update(session_id, {"state": "stopping"})
        row = store.sessions.get(session_id)
    return session_read(row)


@router.get("/api/v1/sessions/{session_id}/results/latest")
def get_api_v1_sessions_session_id_results_latest(
    request: Request, store: StoreDep, session_id: str
) -> dict:
    row = _session_or_404(store, session_id)
    runtime = request.app.state.session_runtimes.get(session_id)
    if runtime and runtime.latest_result:
        return runtime.latest_result
    stored = store.results.latest_for_session(session_id)
    if stored is not None:
        from ..results import result_read
        return result_read(stored)
    raise ApiError(409, "No result is available yet.", code="result_unavailable")

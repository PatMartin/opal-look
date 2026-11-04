"""Monitor CRUD + SSE tail (v1.5): durable desired-state workers."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request

from ..dependencies import StoreDep
from ..errors import ApiError
from ..monitors import (
    monitor_read, recover_monitors, start_monitor, stop_monitor,
    validate_monitor_refs,
)
from ..precondition import check_if_match, require_if_match
from ..schemas import MonitorCreate, MonitorPatch
from ..settings import effective_settings
from ..timeutil import now_iso

router = APIRouter()


def _runtime(request, monitor_id):
    return request.app.state.monitor_runtimes.get(monitor_id)


def _get_monitor_or_404(store: StoreDep, monitor_id: str):
    row = store.monitors.get(monitor_id)
    if row is None:
        raise ApiError(404, f"Unknown monitor: {monitor_id!r}")
    return row


@router.get("/api/v1/monitors/")
def get_api_v1_monitors(request: Request, store: StoreDep) -> list:
    return [
        monitor_read(store, row, _runtime(request, row["monitor_id"]))
        for row in store.monitors.list()
    ]


@router.post("/api/v1/monitors/", status_code=201)
def post_api_v1_monitors(request: Request, store: StoreDep, body: MonitorCreate):
    require_if_match(request)
    if store.monitors.get(body.id) is not None:
        raise ApiError(409, f"Monitor {body.id!r} already exists.")
    app_settings = effective_settings(store)
    if len(store.monitors.list()) >= (app_settings.max_monitors or 8):
        raise ApiError(429, "Monitor quota exceeded.", retryable=True)
    validate_monitor_refs(store, body.source_id, body.pipeline_id, body.conditions)
    with store.write_txn():
        check_if_match(request, store)
        store.monitors.insert({
            "monitor_id": body.id, "name": body.name,
            "source_id": body.source_id, "pipeline_id": body.pipeline_id,
            "enabled": 1 if body.enabled else 0,
            "restart_policy": body.restart_policy,
            "options": json.dumps(
                body.options.model_dump(exclude_unset=True)
                if body.options else None),
            "retention": json.dumps(
                body.retention.model_dump(exclude_unset=True)
                if body.retention else None),
            "conditions": json.dumps(
                [c.model_dump(exclude_unset=True) for c in body.conditions]),
            "publish_events": 1 if body.publish_events else 0,
            "created_at": now_iso(), "revision": 0,
        })
        store.bump_revision()
    if body.enabled:
        start_monitor(store, request.app.state.monitor_runtimes, body.id, request.app)
    row = store.monitors.get(body.id)
    return monitor_read(store, row, _runtime(request, body.id))


@router.get("/api/v1/monitors/{monitor_id}")
def get_api_v1_monitors_monitor_id(
    request: Request, store: StoreDep, monitor_id: str
) -> dict:
    row = _get_monitor_or_404(store, monitor_id)
    return monitor_read(store, row, _runtime(request, monitor_id))


@router.patch("/api/v1/monitors/{monitor_id}")
def patch_api_v1_monitors_monitor_id(
    request: Request, store: StoreDep, monitor_id: str, body: MonitorPatch
) -> dict:
    require_if_match(request)
    row = _get_monitor_or_404(store, monitor_id)
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise ApiError(422, "Patch must include at least one field.")
    new_source = patch.get("source_id", row["source_id"])
    new_pipeline = patch.get("pipeline_id", row["pipeline_id"])
    new_conditions = (
        patch["conditions"]
        if "conditions" in patch else json.loads(row["conditions"]))
    validate_monitor_refs(store, new_source, new_pipeline,
                          _to_conditions(new_conditions))
    with store.write_txn():
        check_if_match(request, store)
        fields: dict = {}
        for key in ("name", "source_id", "pipeline_id", "restart_policy"):
            if key in patch:
                fields[key] = patch[key]
        if "enabled" in patch:
            fields["enabled"] = 1 if patch["enabled"] else 0
        if "publish_events" in patch:
            fields["publish_events"] = 1 if patch["publish_events"] else 0
        if "options" in patch:
            fields["options"] = json.dumps(patch["options"])
        if "retention" in patch:
            fields["retention"] = json.dumps(patch["retention"])
        if "conditions" in patch:
            fields["conditions"] = json.dumps(
                [c.model_dump(exclude_unset=True)
                 if hasattr(c, "model_dump") else c
                 for c in patch["conditions"]])
        if fields:
            store.monitors.update(monitor_id, fields)
            store.monitors.bump_revision(monitor_id)
            store.bump_revision()
    # apply desired-state changes to the worker
    row = store.monitors.get(monitor_id)
    if row["enabled"]:
        start_monitor(store, request.app.state.monitor_runtimes, monitor_id, request.app)
    else:
        stop_monitor(request.app.state.monitor_runtimes, monitor_id)
    return monitor_read(store, row, _runtime(request, monitor_id))


@router.delete("/api/v1/monitors/{monitor_id}", status_code=204)
def delete_api_v1_monitors_monitor_id(
    request: Request, store: StoreDep, monitor_id: str
) -> None:
    require_if_match(request)
    _get_monitor_or_404(store, monitor_id)
    with store.write_txn():
        check_if_match(request, store)
        store.monitors.delete(monitor_id)
        store.bump_revision()
    stop_monitor(request.app.state.monitor_runtimes, monitor_id)
    request.app.state.monitor_runtimes.pop(monitor_id, None)


def _to_conditions(raw):
    from ..schemas import MonitorCondition
    if raw is None:
        return []
    return [c if isinstance(c, MonitorCondition) else MonitorCondition(**c)
            for c in raw]


# -- monitor observation SSE: shared producer + bounded replay (step 20) ---------

@router.get("/api/v1/monitors/{monitor_id}/observations/stream")
async def get_api_v1_monitors_observations_stream(
    request: Request, store: StoreDep, monitor_id: str
):
    import asyncio

    from fastapi.responses import StreamingResponse

    row = _get_monitor_or_404(store, monitor_id)
    runtime = _runtime(request, monitor_id)

    last_id_raw = request.headers.get("last-event-id")
    last_seq = 0
    if last_id_raw is not None:
        try:
            last_seq = int(str(last_id_raw).lstrip("c"))
        except ValueError:
            raise ApiError(422, "Malformed Last-Event-ID header.")
    if runtime is not None and last_seq:
        log = list(runtime.event_log)
        if log and last_seq < log[0][0] - 1:
            # requested cursor older than the replay window: deterministic 409
            raise ApiError(
                409, f"Replay cursor {last_seq} is stale; oldest retained "
                     f"event is {log[0][0]}.", code="replay_expired")

    async def events():
        seq = last_seq
        LF = chr(10)
        try:
            while True:
                if await request.is_disconnected():
                    return
                if runtime is None:
                    yield ": heartbeat" + LF + LF
                    await asyncio.sleep(2.0)
                    continue
                log = list(runtime.event_log)
                emitted = False
                for s_, kind, payload in log:
                    if s_ > seq:
                        seq = s_
                        emitted = True
                        yield ("id: " + str(s_) + LF + "event: " + kind + LF
                               + "data: " + json.dumps(payload) + LF + LF)
                if not emitted:
                    yield ": heartbeat" + LF + LF
                runtime.updated.clear()
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(runtime.updated.wait, 15.0), 15.5)
                except asyncio.TimeoutError:
                    pass
        except Exception:
            return

    return StreamingResponse(events(), media_type="text/event-stream")

"""Monitor CRUD + SSE tail (v1.5): durable desired-state workers."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request

from ..dependencies import StoreDep
from ..errors import ApiError
from ..monitors import (
    monitor_read, recover_monitors, start_monitor, stop_monitor,
)
from ..precondition import check_if_match, require_if_match
from ..schemas import MonitorCreate, MonitorPatch
from ..settings import effective_settings
from ..store import Store
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


def _resolve_monitor_pipeline(store: Store, pipeline_id, profile_id):
    """Explicit pipeline_id -> profile's pipeline_id -> default_pipeline_id."""
    profile = None
    if profile_id is not None:
        profile = store.profiles.get(profile_id)
        if profile is None:
            raise ApiError(404, f"Unknown profile: {profile_id}")
        if pipeline_id is None:
            pipeline_id = json.loads(profile["data"] or "{}").get("pipeline_id")
    if pipeline_id is None:
        pipeline_id = effective_settings(store).default_pipeline_id
    if pipeline_id is None:
        raise ApiError(422, "No pipeline_id supplied and no default configured.")
    if store.pipelines.get(pipeline_id) is None:
        raise ApiError(404, f"Unknown pipeline: {pipeline_id!r}")
    return pipeline_id, profile


@router.post("/api/v1/monitors/", status_code=201)
def post_api_v1_monitors(request: Request, store: StoreDep, body: MonitorCreate):
    require_if_match(request)
    if store.monitors.get(body.id) is not None:
        raise ApiError(409, f"Monitor {body.id!r} already exists.")
    app_settings = effective_settings(store)
    if len(store.monitors.list()) >= (app_settings.max_monitors or 8):
        raise ApiError(429, "Monitor quota exceeded.", retryable=True)
    if store.sources.get(body.source_id) is None:
        raise ApiError(422, f"Unknown source: {body.source_id!r}")
    pipeline_id, profile = _resolve_monitor_pipeline(
        store, body.pipeline_id, body.profile_id)
    retention = None
    if profile is not None:
        retention = json.loads(profile["data"] or "{}").get("retention")
    with store.write_txn():
        check_if_match(request, store)
        store.monitors.insert({
            "monitor_id": body.id, "name": body.name,
            "source_id": body.source_id, "pipeline_id": pipeline_id,
            "enabled": 1 if body.enabled else 0,
            "restart_policy": body.restart_policy,
            "options": json.dumps(
                body.options.model_dump(exclude_unset=True)
                if body.options else None),
            "retention": json.dumps(retention),
            "conditions": "[]",
            "publish_events": 0,
            "created_at": now_iso(), "revision": 0,
        })
        if body.profile_id is not None:
            store.monitors.update(body.id, {"profile_id": body.profile_id})
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
    if store.sources.get(new_source) is None:
        raise ApiError(422, f"Unknown source: {new_source!r}")
    new_profile = patch.get("profile_id", row["profile_id"]
                            if "profile_id" in row.keys() else None)
    new_pipeline, _ = _resolve_monitor_pipeline(
        store, patch.get("pipeline_id", row["pipeline_id"]), new_profile)
    with store.write_txn():
        check_if_match(request, store)
        fields: dict = {}
        for key in ("name", "source_id", "restart_policy"):
            if key in patch:
                fields[key] = patch[key]
        fields["pipeline_id"] = new_pipeline
        if "profile_id" in patch:
            fields["profile_id"] = patch["profile_id"]
        if "enabled" in patch:
            fields["enabled"] = 1 if patch["enabled"] else 0
        if "options" in patch:
            fields["options"] = json.dumps(patch["options"])
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


# -- monitor observation SSE: shared producer + bounded replay (step 20) ---------


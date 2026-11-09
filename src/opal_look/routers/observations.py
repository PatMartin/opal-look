"""Retained observation reads (v1.5): immutable list/show."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request

from ..dependencies import StoreDep
from ..errors import ApiError
from ..timeutil import expired, now_iso

router = APIRouter()


def _body(row) -> dict:
    return json.loads(row["body"])


@router.get("/api/v1/observation/")
def get_api_v1_observations(
    request: Request, store: StoreDep,
    source_id: str | None = Query(default=None),
    monitor_id: str | None = Query(default=None),
    job_id: str | None = Query(default=None),
    after: str | None = Query(default=None),
    before: str | None = Query(default=None),
    task: str | None = Query(default=None),
    label: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    after_key = cursor.split("|", 1) if cursor else None
    rows = store.observations.page(
        now_iso(),
        {"source_id": source_id, "monitor_id": monitor_id, "job_id": job_id,
         "after": after, "before": before, "task": task, "label": label},
        after_key, limit)
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        f"{page[-1]['created_at']}|{page[-1]['observation_id']}"
        if has_more and page else None)
    return {
        "items": [_body(r) for r in page],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@router.get("/api/v1/observation/{observation_id}")
def get_api_v1_observations_observation_id(
    request: Request, store: StoreDep, observation_id: str
) -> dict:
    row = store.observations.get(observation_id)
    if row is None:
        raise ApiError(404, f"Unknown observation: {observation_id!r}")
    if row["expires_at"] is not None and expired(row["expires_at"]):
        raise ApiError(410, f"Observation {observation_id!r} has expired.",
                       code="gone")
    return _body(row)

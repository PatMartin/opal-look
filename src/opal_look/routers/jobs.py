"""Job submission/query/cancel (v1.5): bounded finite work."""

from __future__ import annotations

import hashlib
import json
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..idempotency import request_idempotency_key
from ..jobs import job_read
from ..schemas import JobCreate
from ..settings import effective_settings
from ..timeutil import now_iso

router = APIRouter()

_TERMINAL = {"completed", "failed", "cancelled"}


def _get_job_or_404(store: StoreDep, job_id: str):
    row = store.jobs.get(job_id)
    if row is None:
        raise ApiError(404, f"Unknown job: {job_id!r}")
    return row


@router.get("/api/v1/jobs/")
def get_api_v1_jobs(
    store: StoreDep, kind: str | None = None, state: str | None = None,
    limit: int = 50, cursor: str | None = None
) -> dict:
    limit = min(max(1, limit), 1000)
    rows = store.jobs.list(limit, cursor, kind, state)
    items = [job_read(r) for r in rows[:limit]]
    has_more = len(rows) > limit
    next_cursor = None
    if has_more and items:
        last = rows[limit - 1]
        next_cursor = f"{last['created_at']}|{last['job_id']}"
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


@router.post("/api/v1/jobs/", status_code=202)
def post_api_v1_jobs(request: Request, store: StoreDep, body: JobCreate):
    idem = request_idempotency_key(request)
    fingerprint = None
    if idem is not None:
        fingerprint = hashlib.sha256(
            json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        prior = store.sessions.get_idempotency(idem, now_iso())
        if prior is not None:
            if prior["fingerprint"] != fingerprint:
                raise ApiError(409,
                               "Idempotency-Key was used with a different "
                               "request.", code="idempotency_conflict")
            prior_job = store.jobs.get(prior["session_id"])
            if prior_job is not None:
                return JSONResponse(
                    job_read(prior_job), status_code=202,
                    headers={"Location": f"/api/v1/jobs/{prior_job['job_id']}"})

    # dependency validation
    if body.source_id is not None:
        src = store.sources.get(body.source_id)
        if src is None:
            raise ApiError(404, f"Unknown source: {body.source_id!r}")
        if src["type"] not in ("media", "file", "image"):
            raise ApiError(422, f"source kind {src['type']!r} is not finite")
    if body.media_id is not None and store.media.get(body.media_id) is None:
        raise ApiError(404, f"Unknown media: {body.media_id!r}")
    # upstream kind enum -> internal worker kinds
    kind_map = {"analyze_video": "video_analysis",
                "export_annotated_video": "media_export",
                "extract_clip": "media_export"}
    if body.kind == "extract_clip":
        raise ApiError(422, "extract_clip requires a video decoder "
                            "(not installed)")
    payload = body.model_dump(mode="json", exclude_unset=True)
    payload["kind"] = kind_map[body.kind]
    if body.kind == "analyze_video":
        pipeline_id = body.pipeline_id or effective_settings(
            store).default_pipeline_id
        if body.profile_id is not None:
            prof = store.profiles.get(int(body.profile_id))
            if prof is None:
                raise ApiError(404, f"Unknown profile: {body.profile_id!r}")
            if pipeline_id is None:
                import json as _json
                pipeline_id = _json.loads(
                    prof["data"] or "{}").get("pipeline_id")
        if pipeline_id is None:
            raise ApiError(422, "analyze_video requires pipeline_id or a "
                                "configured default_pipeline_id")
        if store.pipelines.get(pipeline_id) is None:
            raise ApiError(404, f"Unknown pipeline: {pipeline_id!r}")
        payload["pipeline_id"] = pipeline_id
    if (body.output and body.output.format in ("mp4", "webm")
            and body.kind == "export_annotated_video"):
        raise ApiError(422, f"export format {body.output.format!r} requires a "
                            "video encoder (not installed)")

    app_settings = effective_settings(store)
    # bounded: max_jobs running + max_jobs queued in line
    if store.jobs.count_nonterminal() >= (app_settings.max_jobs or 4) * 2:
        raise ApiError(429, "Job concurrency capacity exhausted.",
                       code="capacity_exceeded")

    job_id = f"job-{secrets.token_hex(8)}"
    with store.write_txn():
        store.jobs.insert({
            "job_id": job_id, "kind": body.kind,
            "source_id": body.source_id, "media_id": body.media_id,
            "payload_json": json.dumps(payload), "state": "queued",
            "progress": 0.0, "media_ids": "[]", "created_at": now_iso(),
        })
        if idem is not None and fingerprint is not None:
            store.sessions.put_idempotency(idem, fingerprint, job_id)
        store.bump_revision()
    request.app.state.job_runtime.start(job_id)
    row = store.jobs.get(job_id)
    return JSONResponse(job_read(row), status_code=202,
                        headers={"Location": f"/api/v1/jobs/{job_id}"})


@router.get("/api/v1/jobs/{job_id}")
def get_api_v1_jobs_job_id(store: StoreDep, job_id: str) -> dict:
    return job_read(_get_job_or_404(store, job_id))


@router.post("/api/v1/jobs/{job_id}/cancel")
def post_api_v1_jobs_job_id_cancel(
    store: StoreDep, job_id: str, request: Request
) -> dict:
    row = _get_job_or_404(store, job_id)
    if row["state"] in _TERMINAL:
        raise ApiError(409, f"job {job_id!r} is already {row['state']}",
                       code="invalid_state")
    request.app.state.job_runtime.cancel(job_id)
    if row["state"] == "queued":
        store.jobs.update(job_id, {"state": "cancelled",
                                   "ended_at": now_iso()})
    return job_read(store.jobs.get(job_id))

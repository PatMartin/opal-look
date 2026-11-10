"""Recording start/list/show/stop (v1.5): explicit independent recordings."""

from __future__ import annotations

import hashlib
import json
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..idempotency import request_idempotency_key
from ..precondition import check_if_match, require_if_match
from ..recordings import (
    recording_read, start_recording, stop_recording, validate_recording_refs,
)
from ..schemas import RecordingCreate
from ..settings import effective_settings
from ..timeutil import now_iso

router = APIRouter()

_TERMINAL = {"completed", "failed"}


def _get_recording_or_404(store: StoreDep, recording_id: str):
    row = store.recordings.get(recording_id)
    if row is None:
        raise ApiError(404, f"Unknown recording: {recording_id!r}")
    return row


@router.get("/api/v1/recording/")
def get_api_v1_recordings(
    store: StoreDep, limit: int = 50
) -> list[dict]:
    limit = min(max(1, limit), 1000)
    rows = store.recordings.list(limit)
    return [recording_read(r) for r in rows[:limit]]


@router.post("/api/v1/recording/", status_code=202)
def post_api_v1_recordings(
    request: Request, store: StoreDep, body: RecordingCreate
):
    require_if_match(request)
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
            prior_rec = store.recordings.get(prior["session_id"])
            if prior_rec is not None:
                return JSONResponse(
                    recording_read(prior_rec), status_code=202,
                    headers={"Location":
                             f"/api/v1/recording/{prior_rec['recording_id']}"})

    validate_recording_refs(store, body.source_id, body.pipeline_id,
                            body.include_audio, body.output)
    with store.write_txn():
        check_if_match(request, store)
        recording_id = f"rec-{secrets.token_hex(8)}"
        store.recordings.insert({
            "recording_id": recording_id, "source_id": body.source_id,
            "pipeline_id": body.pipeline_id,
            "include_audio": 1 if body.include_audio else 0,
            "max_duration_seconds": body.max_duration_seconds,
            "output_json": json.dumps(
                body.output.model_dump(exclude_unset=True)
                if body.output else None),
            "state": "starting", "created_at": now_iso(),
        })
        if idem is not None and fingerprint is not None:
            store.sessions.put_idempotency(idem, fingerprint, recording_id)
        store.bump_revision()
    start_recording(store, request.app.state.recording_runtimes,
                    recording_id, request.app)
    row = store.recordings.get(recording_id)
    return JSONResponse(
        recording_read(row), status_code=202,
        headers={"Location": f"/api/v1/recording/{recording_id}"})


@router.get("/api/v1/recording/{recording_id}")
def get_api_v1_recordings_recording_id(
    store: StoreDep, recording_id: str
) -> dict:
    return recording_read(_get_recording_or_404(store, recording_id))


@router.post("/api/v1/recording/{recording_id}/stop")
def post_api_v1_recordings_recording_id_stop(
    request: Request, store: StoreDep, recording_id: str
) -> dict:
    row = _get_recording_or_404(store, recording_id)
    if row["state"] in _TERMINAL:
        # idempotent stop: repeated calls return the finalized recording
        return recording_read(row)
    if row["state"] == "stopping":
        stop_recording(request.app.state.recording_runtimes, recording_id)
        return recording_read(store.recordings.get(recording_id))
    store.recordings.update(recording_id, {"state": "stopping"})
    stop_recording(request.app.state.recording_runtimes, recording_id)
    return recording_read(store.recordings.get(recording_id))

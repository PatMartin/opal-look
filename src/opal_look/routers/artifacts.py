"""Artifact endpoints (upstream): produced output files as resources."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..repositories.artifacts import artifact_read
from ..store import Store
from ..timeutil import now_iso

router = APIRouter()


def _artifact_or_404(store: Store, artifact_id: str):
    row = store.artifacts.get(artifact_id)
    if row is None:
        raise ApiError(404, f"Unknown artifact: {artifact_id!r}")
    if row["expires_at"] <= now_iso():
        raise ApiError(410, f"Artifact {artifact_id!r} has expired.")
    return row


@router.get("/api/v1/artifacts/")
def get_api_v1_artifacts(
    store: StoreDep, kind: str | None = None, source_id: str | None = None,
    job_id: str | None = None,
) -> JSONResponse:
    rows = store.artifacts.list(
        {"kind": kind, "source_id": source_id, "job_id": job_id})
    live = [r for r in rows if r["expires_at"] > now_iso()]
    return JSONResponse([artifact_read(r) for r in live],
                        headers={"ETag": store.config_revision()})


@router.get("/api/v1/artifacts/{artifact_id}")
def get_api_v1_artifacts_artifact_id(
    store: StoreDep, artifact_id: str
) -> JSONResponse:
    return JSONResponse(artifact_read(_artifact_or_404(store, artifact_id)),
                        headers={"ETag": store.config_revision()})


@router.delete("/api/v1/artifacts/{artifact_id}", status_code=204)
def delete_api_v1_artifacts_artifact_id(store: StoreDep, artifact_id: str) -> None:
    row = store.artifacts.get(artifact_id)
    if row is None:
        raise ApiError(404, f"Unknown artifact: {artifact_id!r}")
    with store.write_txn():
        store.artifacts.delete(artifact_id)


@router.get("/api/v1/artifacts/{artifact_id}/content")
def get_api_v1_artifacts_artifact_id_content(store: StoreDep, artifact_id: str):
    row = _artifact_or_404(store, artifact_id)
    path = Path(row["path"])
    if not path.is_file():
        raise ApiError(410, f"Artifact {artifact_id!r} content is gone.")
    return FileResponse(path, media_type=row["mime_type"])

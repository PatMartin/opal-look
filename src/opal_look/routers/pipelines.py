"""Pipeline CRUD (v1.5): simple mode now; stages stored for step 08 DAG."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..engines import ENGINE_REGISTRY, model_runtime
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..schemas import PipelineCreate, PipelinePatch, reject_null_fields
from ..store import Store

router = APIRouter()


def pipeline_read(row) -> dict:
    """Contract Pipeline: {id, name, description?, stages, created_at}.
    Legacy simple-mode rows (model_id+task columns, empty stages) emit a
    synthesized single inference stage so the API shape stays canonical."""
    stages = json.loads(row["stages"])
    if not stages and row["model_id"] is not None:
        stages = [{"id": "inference", "kind": "inference",
                   "model_id": row["model_id"], "task": row["task"]}]
    body = {
        "id": row["pipeline_id"],
        "name": row["name"],
        "stages": stages,
        "created_at": row["created_at"],
    }
    if row["description"] is not None:
        body["description"] = row["description"]
    return body


def _get_or_404(store: Store, pipeline_id: str):
    row = store.pipelines.get(pipeline_id)
    if row is None:
        raise ApiError(404, f"Unknown pipeline: {pipeline_id!r}")
    return row


def _issue(path: str, code: str, message: str) -> dict:
    return {"path": path, "code": code, "message": message, "severity": "error"}


def _issues_422(issues: list[str]) -> None:
    if issues:
        raise ApiError(422, "Pipeline definition is invalid.", details={"issues": issues})


@router.get("/api/v1/pipelines/")
def get_api_v1_pipelines(request: Request, store: StoreDep) -> JSONResponse:
    body = [pipeline_read(r) for r in store.pipelines.list()]
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.post("/api/v1/pipelines/", status_code=201)
def post_api_v1_pipelines(request: Request, store: StoreDep, pipe: PipelineCreate) -> JSONResponse:
    if store.pipelines.get(pipe.id) is not None:
        raise ApiError(409, f"Pipeline {pipe.id!r} already exists.")
    require_if_match(request)
    _issues_422(_check_stages(store, pipe.stages))

    with store.write_txn():
        check_if_match(request, store)
        store.pipelines.insert({
            "pipeline_id": pipe.id, "name": pipe.name,
            "description": pipe.description,
            "model_id": None, "task": None,
            "stages": [st.model_dump(exclude_none=True) for st in pipe.stages],
            "options": {}, "retention": {},
        })
        revision = store.bump_revision()
    return JSONResponse(
        pipeline_read(store.pipelines.get(pipe.id)),
        status_code=201,
        headers={"ETag": revision, "Location": f"/api/v1/pipelines/{pipe.id}"},
    )


def _check_stages(store: Store, stages) -> list[dict]:
    from ..pipeline_validation import validate_stages

    return validate_stages(store, stages)


@router.get("/api/v1/pipelines/{pipeline_id}")
def get_api_v1_pipelines_pipeline_id(request: Request, store: StoreDep, pipeline_id: str) -> JSONResponse:
    row = _get_or_404(store, pipeline_id)
    return JSONResponse(pipeline_read(row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/pipelines/{pipeline_id}")
def patch_api_v1_pipelines_pipeline_id(
    request: Request, store: StoreDep, pipeline_id: str, patch: PipelinePatch
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    require_if_match(request)
    _get_or_404(store, pipeline_id)

    if "stages" in supplied:
        _issues_422(_check_stages(store, patch.stages))

    fields = {}
    for k in ("name", "description"):
        if k in supplied:
            fields[k] = supplied[k]
    if "stages" in supplied:
        fields["stages"] = (
            [{k: v for k, v in st.items() if v is not None} for st in supplied["stages"]]
            if supplied["stages"] is not None else []
        )
    with store.write_txn():
        check_if_match(request, store)
        if fields:
            store.pipelines.update(pipeline_id, fields)
        revision = store.bump_revision()
    return JSONResponse(pipeline_read(store.pipelines.get(pipeline_id)),
                        headers={"ETag": revision})


@router.delete("/api/v1/pipelines/{pipeline_id}", status_code=204)
def delete_api_v1_pipelines_pipeline_id(
    request: Request, response: Response, store: StoreDep, pipeline_id: str
) -> None:
    require_if_match(request)
    _get_or_404(store, pipeline_id)
    if _pipeline_refs(store, pipeline_id):
        raise ApiError(409, f"Pipeline {pipeline_id!r} is referenced by active work.")
    with store.write_txn():
        check_if_match(request, store)
        store.pipelines.delete(pipeline_id)
        response.headers["ETag"] = store.bump_revision()


def _pipeline_refs(store: Store, pipeline_id: str) -> int:
    """Nonterminal sessions/jobs/monitors referencing the pipeline.

    Sessions gain pipeline_id in a later step; tolerate its absence.
    """
    cols = {r["name"] for r in store._conn.execute("PRAGMA table_info(sessions)")}
    if "pipeline_id" not in cols:
        return 0
    return store._conn.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE pipeline_id = ? "
        "AND state NOT IN ('stopped','completed','failed')", (pipeline_id,)
    ).fetchone()["n"]


@router.post("/api/v1/pipelines/validate")
def post_api_v1_pipelines_validate(request: Request, store: StoreDep, pipe: PipelineCreate) -> dict:
    issues = _check_stages(store, pipe.stages)
    return {"valid": not issues, "issues": issues}

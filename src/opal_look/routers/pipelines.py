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
from ..settings import effective_settings
from ..store import Store

router = APIRouter()


def pipeline_read(row) -> dict:
    body = {
        "id": row["pipeline_id"],
        "name": row["name"],
        "revision": str(row["revision"]),
        "created_at": row["created_at"],
    }
    if row["description"] is not None:
        body["description"] = row["description"]
    if row["model_id"] is not None:
        body["model_id"] = row["model_id"]
        body["task"] = row["task"]
    else:
        body["stages"] = json.loads(row["stages"])
    options = json.loads(row["options"])
    if options:
        body["options"] = options
    retention = json.loads(row["retention"])
    if retention:
        body["retention"] = retention
    return body


def _get_or_404(store: Store, pipeline_id: str):
    row = store.pipelines.get(pipeline_id)
    if row is None:
        raise ApiError(404, f"Unknown pipeline: {pipeline_id!r}")
    return row


def _validate_simple(store: Store, model_id: str, task: str, options) -> list[str]:
    """Return validation issue strings (404/422 raised by callers)."""
    issues: list[str] = []
    row = store.models.get(model_id)
    if row is None:
        issues.append(f"model {model_id!r} is not registered")
        return issues
    runtime = model_runtime(store, row)
    if not runtime["enabled"] or not runtime["available"]:
        issues.append(f"model {model_id!r} is not currently available")
    if task not in runtime["tasks"]:
        issues.append(f"task {task!r} is not supported by model {model_id!r}")
    if options and options.engine_options:
        adapter = ENGINE_REGISTRY.get(runtime["engine_id"])
        if adapter is not None:
            issues += adapter.validate_engine_options(options.engine_options)
    return issues


def _check_retention(store: Store, retention) -> list[str]:
    issues: list[str] = []
    if retention and retention.ttl_seconds is not None:
        cap = effective_settings(store).result_retention_hours * 3600
        if retention.ttl_seconds > cap:
            issues.append(
                f"retention ttl_seconds {retention.ttl_seconds} exceeds cap {cap}"
            )
    return issues


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
    if pipe.model_id is not None:
        if store.models.get(pipe.model_id) is None:
            raise ApiError(404, f"Unknown model: {pipe.model_id!r}")
        _issues_422(_validate_simple(store, pipe.model_id, pipe.task, pipe.options))
    else:
        _issues_422(_check_stages(store, pipe.stages))
    _issues_422(_check_retention(store, pipe.retention))

    with store.write_txn():
        check_if_match(request, store)
        store.pipelines.insert({
            "pipeline_id": pipe.id, "name": pipe.name,
            "description": pipe.description,
            "model_id": pipe.model_id, "task": pipe.task,
            "stages": [st.model_dump(exclude_none=True) for st in pipe.stages or []],
            "options": pipe.options.model_dump(exclude_none=True) if pipe.options else {},
            "retention": pipe.retention.model_dump(exclude_none=True) if pipe.retention else {},
        })
        revision = store.bump_revision()
    return JSONResponse(
        pipeline_read(store.pipelines.get(pipe.id)),
        status_code=201,
        headers={"ETag": revision, "Location": f"/api/v1/pipelines/{pipe.id}"},
    )


def _check_stages(store: Store, stages) -> list[str]:
    """Structural checks only; DAG semantics land in step 08."""
    issues: list[str] = []
    ids = [s.id for s in stages]
    if len(ids) != len(set(ids)):
        issues.append("stage ids must be unique")
    for s in stages:
        if s.kind == "inference":
            if s.model_id is None or s.task is None:
                issues.append(f"stage {s.id!r}: inference needs model_id and task")
            elif store.models.get(s.model_id) is None:
                issues.append(f"stage {s.id!r}: model {s.model_id!r} is not registered")
    return issues


@router.get("/api/v1/pipelines/{pipeline_id}")
def get_api_v1_pipelines_pipeline_id(request: Request, store: StoreDep, pipeline_id: str) -> JSONResponse:
    row = _get_or_404(store, pipeline_id)
    return JSONResponse(pipeline_read(row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/pipelines/{pipeline_id}")
def patch_api_v1_pipelines_pipeline_id(
    request: Request, store: StoreDep, pipeline_id: str, patch: PipelinePatch
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    # Explicit null is meaningful here (clears a field / mode switch), so no
    # reject_null_fields on nullable keys.
    require_if_match(request)
    row = _get_or_404(store, pipeline_id)

    # Resolve the post-patch definition, then require a valid oneOf mode.
    merged = {
        "model_id": supplied["model_id"] if "model_id" in supplied else row["model_id"],
        "task": supplied["task"] if "task" in supplied else row["task"],
        "stages": supplied["stages"] if "stages" in supplied else json.loads(row["stages"]) or None,
    }
    simple = merged["model_id"] is not None and merged["task"] is not None
    has_stages = bool(merged["stages"])
    if (merged["model_id"] is None) != (merged["task"] is None) or simple == has_stages:
        raise ApiError(422, "Resolved pipeline must be simple (model_id+task) "
                            "or advanced (stages), exactly one mode.")
    if simple:
        if store.models.get(merged["model_id"]) is None:
            raise ApiError(404, f"Unknown model: {merged['model_id']!r}")
        _issues_422(_validate_simple(store, merged["model_id"], merged["task"],
                                     patch.options))
    elif has_stages:
        from ..schemas import PipelineStage
        _issues_422(_check_stages(store, [PipelineStage(**s) if isinstance(s, dict) else s
                                          for s in merged["stages"]]))
    _issues_422(_check_retention(store, patch.retention))

    fields = {}
    for k in ("name", "description", "model_id", "task"):
        if k in supplied:
            fields[k] = supplied[k]
    if "stages" in supplied:
        fields["stages"] = (
            [{k: v for k, v in st.items() if v is not None} for st in supplied["stages"]]
            if supplied["stages"] is not None else None
        )
    if "options" in supplied:
        fields["options"] = patch.options.model_dump(exclude_none=True)
    if "retention" in supplied:
        fields["retention"] = patch.retention.model_dump(exclude_none=True)
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
    issues: list[str] = []
    if pipe.model_id is not None:
        if store.models.get(pipe.model_id) is None:
            issues.append(f"model {pipe.model_id!r} is not registered")
        else:
            issues += _validate_simple(store, pipe.model_id, pipe.task, pipe.options)
    else:
        issues += _check_stages(store, pipe.stages)
    issues += _check_retention(store, pipe.retention)
    return {
        "valid": not issues,
        "issues": [{"severity": "error", "message": m, "path": ""} for m in issues],
    }

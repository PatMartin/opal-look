"""Rule endpoints: standalone detection/event conditions scoped to a source."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..repositories.rules import rule_read
from ..schemas import IDENTIFIER_PATTERN
from ..store import Store

router = APIRouter()

RULE_KINDS = frozenset({
    "object_appears", "object_disappears", "enters_zone", "exits_zone",
    "line_crosses", "count_threshold", "dwell_time",
})
_ZONE_KINDS = frozenset({"enters_zone", "exits_zone", "line_crosses"})


class RuleCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    name: str = Field(min_length=1)
    source_id: str = Field(min_length=1, max_length=128)
    zone_id: str | None = Field(default=None, min_length=1, max_length=128)
    kind: str
    class_filters: list[str] | None = Field(default=None)
    threshold: float | None = Field(default=None, ge=0)
    minimum_duration_ms: int | None = Field(default=None, ge=0)
    cooldown_ms: int | None = Field(default=None, ge=0)
    enabled: bool = Field(default=True)
    capture_on_match: bool = Field(default=False)
    clip_on_match: bool = Field(default=False)


class RulePatch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    source_id: str | None = Field(default=None, min_length=1, max_length=128)
    zone_id: str | None = Field(default=None, min_length=1, max_length=128)
    kind: str | None = Field(default=None)
    class_filters: list[str] | None = Field(default=None)
    threshold: float | None = Field(default=None, ge=0)
    minimum_duration_ms: int | None = Field(default=None, ge=0)
    cooldown_ms: int | None = Field(default=None, ge=0)
    enabled: bool | None = Field(default=None)
    capture_on_match: bool | None = Field(default=None)
    clip_on_match: bool | None = Field(default=None)


def _get_rule_or_404(store: Store, rule_id: str):
    row = store.rules.get(rule_id)
    if row is None:
        raise ApiError(404, f"Unknown rule: {rule_id!r}")
    return row


def _validate_refs(store: Store, source_id: str, zone_id, kind: str) -> None:
    if kind not in RULE_KINDS:
        raise ApiError(422, f"Unknown rule kind: {kind!r}")
    if store.sources.get(source_id) is None:
        raise ApiError(422, f"Unknown source: {source_id!r}")
    if kind in _ZONE_KINDS and not zone_id:
        raise ApiError(422, f"zone_id is required for {kind} rules")
    if zone_id is not None:
        zrow = store.zones.get(zone_id)
        if zrow is None:
            raise ApiError(422, f"Unknown zone: {zone_id!r}")
        if zrow["source_id"] != source_id:
            raise ApiError(422, f"Zone {zone_id!r} belongs to a different source")


@router.get("/api/v1/rules/")
def get_api_v1_rules(store: StoreDep, source_id: str | None = None) -> JSONResponse:
    rows = (store.rules.list_for_source(source_id) if source_id
            else store.rules.list())
    return JSONResponse([rule_read(r) for r in rows],
                        headers={"ETag": store.config_revision()})


@router.post("/api/v1/rules/", status_code=201)
def post_api_v1_rules(request: Request, store: StoreDep, body: RuleCreate) -> JSONResponse:
    require_if_match(request)
    _validate_refs(store, body.source_id, body.zone_id, body.kind)
    with store.write_txn():
        check_if_match(request, store)
        try:
            store.rules.insert(body.model_dump() | {"rule_id": body.id})
        except sqlite3.IntegrityError:
            raise ApiError(409, f"Rule already exists: {body.id!r}")
        revision = store.bump_revision()
    return JSONResponse(rule_read(store.rules.get(body.id)),
                        status_code=201, headers={"ETag": revision})


@router.get("/api/v1/rules/{rule_id}")
def get_api_v1_rules_rule_id(store: StoreDep, rule_id: str) -> JSONResponse:
    return JSONResponse(rule_read(_get_rule_or_404(store, rule_id)),
                        headers={"ETag": store.config_revision()})


@router.patch("/api/v1/rules/{rule_id}")
def patch_api_v1_rules_rule_id(
    request: Request, store: StoreDep, rule_id: str, body: RulePatch
) -> JSONResponse:
    require_if_match(request)
    row = _get_rule_or_404(store, rule_id)
    supplied = body.model_dump(exclude_unset=True)
    if not supplied:
        raise ApiError(422, "Empty rule patches are not allowed.")
    kind = supplied.get("kind") or row["kind"]
    source_id = supplied.get("source_id") or row["source_id"]
    zone_id = supplied.get("zone_id", row["zone_id"])
    _validate_refs(store, source_id, zone_id, kind)
    fields = {api: v for api, v in supplied.items()
              if api in ("name", "source_id", "zone_id", "kind",
                         "class_filters", "threshold", "minimum_duration_ms",
                         "cooldown_ms", "enabled", "capture_on_match",
                         "clip_on_match")}
    with store.write_txn():
        check_if_match(request, store)
        if fields:
            store.rules.update(rule_id, fields)
        revision = store.bump_revision()
    return JSONResponse(rule_read(store.rules.get(rule_id)),
                        headers={"ETag": revision})


@router.delete("/api/v1/rules/{rule_id}", status_code=204)
def delete_api_v1_rules_rule_id(
    request: Request, response: Response, store: StoreDep, rule_id: str
) -> None:
    require_if_match(request)
    _get_rule_or_404(store, rule_id)
    with store.write_txn():
        check_if_match(request, store)
        store.rules.delete(rule_id)
        response.headers["ETag"] = store.bump_revision()

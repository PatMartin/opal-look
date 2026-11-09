"""Zone endpoints: standalone named regions scoped to a source."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..repositories.zones import zone_read
from ..schemas import IDENTIFIER_PATTERN, Point
from ..store import Store

router = APIRouter()


class ZoneCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    source_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1)
    kind: str
    points: list[Point] = Field(min_length=2)
    enabled: bool = Field(default=True)

    @model_validator(mode="after")
    def _check_geometry(self) -> "ZoneCreate":
        _check_zone_geometry(self.kind, self.points)
        return self


class ZonePatch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    points: list[Point] | None = Field(default=None)
    kind: str | None = Field(default=None)
    enabled: bool | None = Field(default=None)


def _check_zone_geometry(kind: str, points: list) -> None:
    if kind not in ("polygon", "line"):
        raise ApiError(422, f"Unknown zone kind: {kind!r}")
    if kind == "polygon" and len(points) < 3:
        raise ApiError(422, "polygon zones require at least 3 points")
    if kind == "line" and len(points) != 2:
        raise ApiError(422, "line zones require exactly 2 points")


def _get_zone_or_404(store: Store, zone_id: str):
    row = store.zones.get(zone_id)
    if row is None:
        raise ApiError(404, f"Unknown zone: {zone_id!r}")
    return row


@router.get("/api/v1/zone/")
def get_api_v1_zones(store: StoreDep, source_id: str | None = None) -> JSONResponse:
    rows = (store.zones.list_for_source(source_id) if source_id
            else store.zones.list())
    return JSONResponse([zone_read(r) for r in rows],
                        headers={"ETag": store.config_revision()})


@router.post("/api/v1/zone/", status_code=201)
def post_api_v1_zones(request: Request, store: StoreDep, body: ZoneCreate) -> JSONResponse:
    require_if_match(request)
    if store.sources.get(body.source_id) is None:
        raise ApiError(422, f"Unknown source: {body.source_id!r}")
    with store.write_txn():
        check_if_match(request, store)
        try:
            store.zones.insert({
                "zone_id": body.id, "source_id": body.source_id,
                "name": body.name, "kind": body.kind,
                "points": [p.model_dump() for p in body.points],
                "enabled": body.enabled,
            })
        except sqlite3.IntegrityError:
            raise ApiError(409, f"Zone already exists: {body.id!r}")
        revision = store.bump_revision()
    return JSONResponse(zone_read(store.zones.get(body.id)),
                        status_code=201, headers={"ETag": revision})


@router.get("/api/v1/zone/{zone_id}")
def get_api_v1_zones_zone_id(store: StoreDep, zone_id: str) -> JSONResponse:
    return JSONResponse(zone_read(_get_zone_or_404(store, zone_id)),
                        headers={"ETag": store.config_revision()})


@router.patch("/api/v1/zone/{zone_id}")
def patch_api_v1_zones_zone_id(
    request: Request, store: StoreDep, zone_id: str, body: ZonePatch
) -> JSONResponse:
    require_if_match(request)
    row = _get_zone_or_404(store, zone_id)
    supplied = body.model_dump(exclude_unset=True)
    if any(v is None for v in supplied.values()):
        raise ApiError(422, "Explicit null values are not allowed in updates.")
    if not supplied:
        raise ApiError(422, "Empty zone patches are not allowed.")
    kind = supplied.get("kind") or row["kind"]
    points = supplied.get("points")
    _check_zone_geometry(kind, points if points is not None
                         else __import__("json").loads(row["points"]))
    fields = {}
    for api, col in (("name", "name"), ("kind", "kind"),
                     ("points", "points"), ("enabled", "enabled")):
        if api in supplied:
            fields[col] = ([p.model_dump() for p in supplied[api]]
                           if api == "points" else supplied[api])
    with store.write_txn():
        check_if_match(request, store)
        store.zones.update(zone_id, fields)
        revision = store.bump_revision()
    return JSONResponse(zone_read(store.zones.get(zone_id)),
                        headers={"ETag": revision})


@router.delete("/api/v1/zone/{zone_id}", status_code=204)
def delete_api_v1_zones_zone_id(
    request: Request, response: Response, store: StoreDep, zone_id: str
) -> None:
    require_if_match(request)
    _get_zone_or_404(store, zone_id)
    with store.write_txn():
        check_if_match(request, store)
        store.zones.delete(zone_id)
        response.headers["ETag"] = store.bump_revision()

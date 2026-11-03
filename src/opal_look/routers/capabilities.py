"""Capability discovery endpoint (v1.5)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..capabilities import capability_catalog
from ..dependencies import StoreDep

router = APIRouter()


@router.get("/api/v1/capabilities/")
def get_api_v1_capabilities(request: Request, store: StoreDep) -> dict:
    return capability_catalog(store)

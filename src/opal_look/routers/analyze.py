"""Synchronous one-shot analysis endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..analysis import run_analysis
from ..dependencies import StoreDep
from ..schemas import AnalyzeRequest

router = APIRouter()


@router.post("/api/v1/analyze")
async def post_api_v1_analyze(request: Request, store: StoreDep, body: AnalyzeRequest) -> dict:
    return await run_analysis(store, body, request.app.state.frame_cache)

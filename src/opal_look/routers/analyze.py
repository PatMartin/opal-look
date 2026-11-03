"""Synchronous one-shot analysis endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..analysis import run_analysis, run_analysis_v15
from ..dependencies import StoreDep
from ..schemas import AnalyzeRequest, AnalyzeSubmission

router = APIRouter()


@router.post("/api/v1/analyze")
async def post_api_v1_analyze(request: Request, store: StoreDep, body: AnalyzeRequest) -> dict:
    return await run_analysis(store, body, request.app.state.frame_cache)


@router.post("/api/v1/analyze/")
async def post_api_v1_analyze_v15(request: Request, store: StoreDep, body: AnalyzeSubmission) -> dict:
    """v1.5 one-shot analysis: pipeline + SourceInput -> observations."""
    return await run_analysis_v15(store, body, request.app.state.frame_cache)

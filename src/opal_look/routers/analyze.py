"""Synchronous one-shot analysis endpoint."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile

from ..analysis import run_analysis, run_analysis_v15, run_image_analysis
from ..dependencies import StoreDep
from ..schemas import AnalyzeRequest, AnalyzeSubmission, ImageAnalyzeOptions

router = APIRouter()


@router.post("/api/v1/analyze")
async def post_api_v1_analyze(request: Request, store: StoreDep, body: AnalyzeRequest) -> dict:
    return await run_analysis(store, body, request.app.state.frame_cache)


@router.post("/api/v1/analyze/")
async def post_api_v1_analyze_v15(request: Request, store: StoreDep, body: AnalyzeSubmission) -> dict:
    """v1.5 one-shot analysis: pipeline + SourceInput -> observations."""
    return await run_analysis_v15(store, body, request.app.state.frame_cache)


def _jpeg(image) -> bytes:
    import io as _io
    buf = _io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@router.post("/api/v1/analyze/image")
async def post_api_v1_analyze_image(
    request: Request, store: StoreDep,
    image: UploadFile = File(),
    request_part: str | None = Form(default=None, alias="request"),
):
    """v1.5 multipart analyze: image file + optional JSON 'request' part."""
    import json as _json

    from PIL import Image, ImageOps
    import io as _io

    from ..errors import ApiError
    from ..media import detect_and_decode
    from ..settings import effective_settings
    from ..correlation import current_ids
    from fastapi.responses import JSONResponse, Response

    app_settings = effective_settings(store)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > app_settings.max_upload_bytes:
        raise ApiError(413, "Upload exceeds the configured size limit.")
    data = await image.read()
    if not data:
        raise ApiError(422, "multipart 'image' file part is required.")
    if len(data) > app_settings.max_upload_bytes:
        raise ApiError(413, "Upload exceeds the configured size limit.")
    detect_and_decode(data, app_settings.max_image_pixels)  # 415/413/422 policy
    try:
        decoded = ImageOps.exif_transpose(
            Image.open(_io.BytesIO(data))).convert("RGB")
    except Exception:
        raise ApiError(422, "Image bytes could not be decoded.")

    if request_part is None or request_part.strip() == "":
        opts = ImageAnalyzeOptions()
    else:
        try:
            opts = ImageAnalyzeOptions.model_validate(_json.loads(request_part))
        except Exception as exc:
            raise ApiError(422, f"Invalid JSON 'request' part: {exc}",
                           details={"errors": str(exc)})

    ids = current_ids()
    result = await run_image_analysis(
        store, decoded, opts, ids.request_id, ids.transaction_id, app_settings)

    accept = request.headers.get("accept", "")
    presentation = result.pop("_presentation")
    if "image/jpeg" in accept:
        out = presentation if presentation is not None else decoded
        return Response(_jpeg(out), media_type="image/jpeg")
    return JSONResponse(result)

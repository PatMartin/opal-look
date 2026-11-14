"""Single-image prediction endpoint (engine required)."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from PIL import Image

from ..dependencies import StoreDep
from ..engines import (ENGINE_REGISTRY, EngineUnavailable, ModelNotFound,
                       engine_gate)
from ..errors import ApiError
from ..schemas import PredictRequest
from ..settings import effective_settings

router = APIRouter()

_FETCH_TIMEOUT = 10.0


def _image_bytes(source: str, max_bytes: int) -> bytes:
    """Fetch image bytes from a local path or http(s) URI with size cap."""
    if source.startswith(("http://", "https://")):
        try:
            resp = httpx.get(source, timeout=_FETCH_TIMEOUT, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise ApiError(422, f"Cannot fetch image source: {exc}")
        if resp.status_code != 200:
            raise ApiError(422, f"Image source returned {resp.status_code}.")
        data = resp.content
    else:
        path = Path(source)
        if not path.is_file():
            raise ApiError(422, f"Image source not found: {source!r}")
        data = path.read_bytes()
    if len(data) > max_bytes:
        raise ApiError(413, f"Image exceeds max_upload_bytes ({max_bytes}).")
    return data


def _decode(data: bytes, max_pixels: int):
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise ApiError(422, "Source is not a decodable image.")
    if img.width * img.height > max_pixels:
        raise ApiError(413, f"Image exceeds max_image_pixels ({max_pixels}).")
    return img


@router.post("/api/v1/predict")
def post_api_v1_predict(request: Request, store: StoreDep,
                        body: PredictRequest) -> JSONResponse:
    adapter = ENGINE_REGISTRY.get(body.engine_id)
    if adapter is None:
        raise ApiError(404, f"Unknown engine: {body.engine_id!r}")
    engine_gate(store, adapter)

    model = next((m for m in adapter.models()
                  if m["model_id"] == body.model_id), None)
    if model is None:
        raise ApiError(404, f"Unknown model: {body.model_id!r}")
    if not model.get("loaded"):
        raise ApiError(409, f"Model {body.model_id!r} is not loaded.")

    if body.device_id is not None and not any(
            d["device_id"] == body.device_id for d in adapter.hardware()):
        raise ApiError(422, f"Unknown device: {body.device_id!r}")
    errors = adapter.validate_engine_options(body.engine_options)
    if errors:
        raise ApiError(422, "Invalid engine options.", details=errors)

    limits = effective_settings(store)
    data = _image_bytes(body.source, limits.max_upload_bytes)
    image = _decode(data, limits.max_image_pixels)

    try:
        result = adapter.predict(
            image=image, model_id=body.model_id,
            confidence=body.confidence, device_id=body.device_id,
            engine_options=body.engine_options,
            include_native=body.include_native)
    except ModelNotFound:
        raise ApiError(404, f"Unknown model: {body.model_id!r}")
    except EngineUnavailable as exc:
        raise ApiError(503, str(exc))

    out = {
        "engine_id": body.engine_id,
        "model_id": body.model_id,
        "image": {"width": image.width, "height": image.height},
        "detections": result["detections"],
        "execution_id": uuid.uuid4().hex,
    }
    if body.include_native and "native" in result:
        out["native"] = result["native"]
    return JSONResponse(out)

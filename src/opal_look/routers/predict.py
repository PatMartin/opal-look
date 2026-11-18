"""Single-image prediction endpoint (engine required)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..engines import (EngineUnavailable, ModelNotFound,
                       engine_gate)
from ..errors import ApiError
from ..schemas import PredictRequest
from ..settings import effective_settings
from ..source_policy import (HTTP_SCHEMES, SourcePolicy, decode_image,
                             fetch_http, read_local)

router = APIRouter()


def _load_image(source: str, policy: SourcePolicy,
                max_bytes: int, max_pixels: int):
    """Policy-checked, byte-bounded fetch, then header-bound decode."""
    if source.startswith(tuple(f"{s}://" for s in HTTP_SCHEMES)):
        data = fetch_http(policy, source, max_bytes)
    else:
        data = read_local(policy.local_path(source), max_bytes)
    return decode_image(data, max_pixels)


@router.post("/api/v1/predict")
def post_api_v1_predict(request: Request, store: StoreDep,
                        body: PredictRequest) -> JSONResponse:
    adapter = request.app.state.engine_registry.get(body.engine_id)
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
    image = _load_image(body.source, SourcePolicy.from_settings(limits),
                        limits.max_upload_bytes, limits.max_image_pixels)

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

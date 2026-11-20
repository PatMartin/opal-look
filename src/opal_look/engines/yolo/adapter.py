"""Remote Ultralytics YOLO adapter.

Implements the EngineAdapter protocol by proxying to a standalone
opal-look-yolo service (openapi/engines/opal_look_yolo_v0.1.0.yaml). Connection
details come from engine config (seeded from OPAL_LOOK_ENGINE_YOLO_* env);
the bearer token is env-only.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from .. import EngineUnavailable, ModelNotFound
from .env import ENGINE_ID, env_config, env_token


class YoloRemoteAdapter:
    """EngineAdapter backed by a remote opal-look-yolo service."""

    engine_id = ENGINE_ID
    name = "Ultralytics YOLO (remote)"
    execution = "remote"

    # Native YOLO predict options declared by the adapter contract.
    _ENGINE_OPTION_KEYS = {"agnostic_nms", "augment", "classes", "half",
                           "imgsz", "iou", "max_det", "verbose"}

    _OPTIONS_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "base_url": {"type": "string", "minLength": 1},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
        },
    }

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport
        self._clients: dict[tuple[Any, ...], httpx.Client] = {}
        self._sequence = 0

    # -- connection ------------------------------------------------------

    def _client(self, config: dict[str, Any] | None) -> httpx.Client:
        cfg = config if config is not None else env_config()
        url = cfg.get("base_url")
        if not url:
            raise EngineUnavailable(
                "yolo adapter is not configured "
                "(set OPAL_LOOK_ENGINE_YOLO_BASE_URL)")
        timeout = float(cfg.get("timeout_seconds") or 30.0)
        token = env_token()
        key = (url, timeout, token)
        client = self._clients.get(key)
        if client is None:
            headers = ({"Authorization": f"Bearer {token}"}
                       if token else {})
            client = httpx.Client(base_url=url.rstrip("/"), timeout=timeout,
                                  headers=headers,
                                  transport=self._transport)
            self._clients[key] = client
        return client

    def _call(self, config: dict[str, Any] | None, method: str, path: str,
              model_id: str | None = None, **kwargs: Any) -> Any:
        try:
            resp = self._client(config).request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise EngineUnavailable(
                f"yolo adapter unreachable: {exc}") from exc
        if resp.status_code == 404:
            if model_id is not None:
                raise ModelNotFound(model_id)
            raise EngineUnavailable(f"yolo adapter has no {path} route")
        if resp.status_code in (401, 403):
            raise EngineUnavailable(
                "yolo adapter rejected credentials "
                "(check OPAL_LOOK_ENGINE_YOLO_TOKEN)")
        if resp.status_code >= 400:
            raise EngineUnavailable(
                f"yolo adapter returned HTTP {resp.status_code}")
        return resp.json() if resp.content else {}

    # -- description / config --------------------------------------------

    def capabilities(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        try:
            caps = self._call(None, "GET", "/api/v1/engine/yolo/capabilities")
        except EngineUnavailable:
            pass
        return {
            "tasks": caps.get("tasks") or ["detection"],
            "tracking": False,
            "device_types": caps.get("supported_devices") or ["cpu"],
            "source_types": ["image"],
            "engine_options": sorted(
                caps.get("options_schema", {}).get("properties")
                or self._ENGINE_OPTION_KEYS),
            "annotation": True,
        }

    def options_schema(self) -> dict[str, Any]:
        return dict(self._OPTIONS_SCHEMA)

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        allowed = set(self._OPTIONS_SCHEMA["properties"])
        for key in config:
            if key not in allowed:
                errors.append(f"unknown option: {key}")
        url = config.get("base_url")
        if url is not None and not (
                isinstance(url, str)
                and url.startswith(("http://", "https://"))):
            errors.append("base_url must be an http(s) URL")
        timeout = config.get("timeout_seconds")
        if timeout is not None and not (
                isinstance(timeout, (int, float)) and timeout > 0):
            errors.append("timeout_seconds must be a positive number")
        return errors

    def metadata(self) -> dict[str, Any]:
        return {
            "description": "Remote Ultralytics YOLO adapter service",
            "adapter": "remote",
            "version": "2.0.0-mvp-plus",
        }

    def probe(self, config: dict[str, Any], enabled: bool
              ) -> tuple[bool, str | None]:
        if not enabled:
            return False, "disabled"
        try:
            engine = self._call(config, "GET", "/api/v1/engine/yolo")
        except EngineUnavailable as exc:
            return False, str(exc)
        if engine.get("available"):
            return True, None
        return False, "adapter service reports unavailable"

    def validate_engine_options(self, options: dict[str, Any]
                                ) -> list[str]:
        return [f"unknown engine option: {key}" for key in options
                if key not in self._ENGINE_OPTION_KEYS]

    # -- MVP ops ----------------------------------------------------------

    def hardware(self) -> list[dict[str, Any]]:
        return self._call(None, "GET", "/api/v1/hardware/")

    def models(self) -> list[dict[str, Any]]:
        return [self._map_model(m)
                for m in self._call(None, "GET", "/api/v1/model/")]

    def load_model(self, model_id: str, device_id: str | None
                   ) -> dict[str, Any]:
        payload = {"device": device_id} if device_id else {}
        data = self._call(None, "POST", f"/api/v1/model/{model_id}/load",
                          json=payload, model_id=model_id)
        return self._map_model(data)

    def unload_model(self, model_id: str) -> dict[str, Any]:
        data = self._call(None, "POST", f"/api/v1/model/{model_id}/unload",
                          model_id=model_id)
        return self._map_model(data)

    def predict(self, image: Any, model_id: str, confidence: float,
                device_id: str | None, engine_options: dict[str, Any],
                include_native: bool) -> dict[str, Any]:
        self._sequence += 1
        envelope = {
            "stream_id": "opal-look",
            "frame_id": uuid.uuid4().hex,
            "sequence": self._sequence,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "image": {"width": image.width, "height": image.height},
        }
        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        data: dict[str, str] = {
            "frame": json.dumps(envelope),
            "model_id": model_id,
            "confidence": str(confidence),
            "include_native": "true" if include_native else "false",
        }
        if device_id:
            data["device"] = device_id
        if engine_options:
            data["engine_options"] = json.dumps(engine_options)
        result = self._call(
            None, "POST", "/api/v1/predict/frame",
            data=data, files={"image": ("frame.jpg", buf.getvalue(),
                                        "image/jpeg")},
            model_id=model_id)
        out: dict[str, Any] = {"detections": result.get("detections", [])}
        if include_native and result.get("native") is not None:
            out["native"] = result["native"]
        return out

    def _map_model(self, model: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(model.get("metadata") or {})
        if model.get("weights_sha256"):
            metadata["weights_sha256"] = model["weights_sha256"]
        return {
            "model_id": model["model_id"],
            "engine_id": self.engine_id,
            "tasks": model.get("tasks", []),
            "loaded": model.get("loaded", False),
            "available": model.get("available", True),
            "metadata": metadata,
        }

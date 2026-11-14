"""Engine adapter registry.

Engines are installed/discovered by the implementation and advertised via
/api/v1/engine/. The built-in ``synthetic`` adapter produces deterministic,
schema-shaped outputs for every task without hardware or ML dependencies,
so the full contract is exercisable end to end. Real adapters (e.g.
Ultralytics) slot behind the same interface.

Stored per engine: enabled flag + non-secret config (adapter-validated keys).
Probed at read time: availability, message, capabilities.
"""

from __future__ import annotations

import json
import random
import sqlite3
from typing import Any, Protocol

from .store import Store


class EngineUnavailable(Exception):
    """Adapter cannot execute inference right now (-> 503)."""


class ModelNotFound(Exception):
    """Adapter does not own the requested model (-> 404)."""


TASKS = ["detection"]
SOURCE_TYPES = ["rtsp"]

_SYNTHETIC_CLASSES = [
    {"class_id": 0, "label": "person"},
    {"class_id": 1, "label": "car"},
    {"class_id": 2, "label": "dog"},
]


class EngineAdapter(Protocol):
    engine_id: str
    name: str
    execution: str  # local | remote

    def capabilities(self) -> dict[str, Any]: ...
    def probe(self, config: dict[str, Any], enabled: bool) -> tuple[bool, str | None]: ...
    def options_schema(self) -> dict[str, Any]: ...
    def validate_config(self, config: dict[str, Any]) -> list[str]: ...
    def metadata(self) -> dict[str, Any]: ...
    def validate_engine_options(self, options: dict[str, Any]) -> list[str]: ...

    # MVP surface: engine-local hardware, federated model catalog, prediction.
    def hardware(self) -> list[dict[str, Any]]: ...
    def models(self) -> list[dict[str, Any]]: ...
    def load_model(self, model_id: str, device_id: str | None) -> dict[str, Any]: ...
    def unload_model(self, model_id: str) -> dict[str, Any]: ...
    def predict(
        self,
        image: Any,
        model_id: str,
        confidence: float,
        device_id: str | None,
        engine_options: dict[str, Any],
        include_native: bool,
    ) -> dict[str, Any]: ...


class SyntheticAdapter:
    """Deterministic built-in engine for development and contract tests."""

    engine_id = "synthetic"
    name = "Synthetic deterministic engine"
    execution = "local"

    def __init__(self) -> None:
        self._loaded: dict[str, bool] = {}

    _CONFIG_KEYS = {"seed", "force_unavailable"}

    def capabilities(self) -> dict[str, Any]:
        return {
            "tasks": list(TASKS),
            "tracking": True,
            "device_types": ["cpu"],
            "source_types": list(SOURCE_TYPES),
            "engine_options": sorted(self._ENGINE_OPTION_KEYS),
            "annotation": True,
        }

    _OPTIONS_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "seed": {"type": "integer"},
            "force_unavailable": {"type": "boolean"},
        },
    }

    def options_schema(self) -> dict[str, Any]:
        return dict(self._OPTIONS_SCHEMA)

    def probe(self, config: dict[str, Any], enabled: bool) -> tuple[bool, str | None]:
        if not enabled:
            return False, "engine disabled"
        if config.get("force_unavailable"):
            return False, "forced unavailable by configuration"
        return True, None

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors = []
        for key, value in config.items():
            if key not in self._CONFIG_KEYS:
                errors.append(f"unknown engine config key: {key}")
            elif key == "seed" and not isinstance(value, int):
                errors.append("config key 'seed' must be an integer")
            elif key == "force_unavailable" and not isinstance(value, bool):
                errors.append("config key 'force_unavailable' must be a boolean")
        return errors

    def metadata(self) -> dict[str, Any]:
        return {"adapter": "synthetic", "version": "0.1.0"}

    _MODEL_ID = "synthetic-det"

    def hardware(self) -> list[dict[str, Any]]:
        return [{"device_id": "cpu", "type": "cpu", "available": True,
                 "name": "Host CPU"}]

    def models(self) -> list[dict[str, Any]]:
        return [{
            "model_id": self._MODEL_ID,
            "engine_id": self.engine_id,
            "tasks": ["detection"],
            "loaded": self._loaded.get(self._MODEL_ID, False),
            "available": True,
            "metadata": {"adapter": "synthetic",
                         "classes": [c["label"] for c in _SYNTHETIC_CLASSES]},
        }]

    def load_model(self, model_id: str, device_id: str | None) -> dict[str, Any]:
        self._require_model(model_id)
        if device_id not in (None, "cpu"):
            raise EngineUnavailable(f"unknown device: {device_id!r}")
        self._loaded[self._MODEL_ID] = True
        return self.models()[0]

    def unload_model(self, model_id: str) -> dict[str, Any]:
        self._require_model(model_id)
        self._loaded[self._MODEL_ID] = False
        return self.models()[0]

    def _require_model(self, model_id: str) -> None:
        if model_id != self._MODEL_ID:
            raise ModelNotFound(model_id)

    _ENGINE_OPTION_KEYS = {"seed", "fail", "latency_ms"}

    def validate_engine_options(self, options: dict[str, Any]) -> list[str]:
        errors = []
        for key, value in options.items():
            if key not in self._ENGINE_OPTION_KEYS:
                errors.append(f"unknown engine option: {key}")
            elif key in ("seed", "latency_ms") and not isinstance(value, int):
                errors.append(f"engine option {key!r} must be an integer")
            elif key == "latency_ms" and value < 0:
                errors.append("engine option 'latency_ms' must be >= 0")
            elif key == "fail" and not isinstance(value, bool):
                errors.append("engine option 'fail' must be a boolean")
        return errors

    def predict(
        self,
        image: Any,
        model_id: str,
        confidence: float,
        device_id: str | None,
        engine_options: dict[str, Any],
        include_native: bool,
    ) -> dict[str, Any]:
        """Deterministic contract-normalized detections (xyxy pixels)."""
        self._require_model(model_id)
        width, height = image.size
        if device_id not in (None, "cpu"):
            raise EngineUnavailable(f"unknown device: {device_id!r}")
        if engine_options.get("fail"):
            raise EngineUnavailable("synthetic engine forced failure")
        latency = engine_options.get("latency_ms") or 0
        if latency:
            import time

            time.sleep(min(latency, 10_000) / 1000)
        rng = random.Random((engine_options.get("seed") or 0) ^ (width * 31 + height))
        detections = []
        for _ in range(rng.randint(1, 3)):
            cls = rng.choice(_SYNTHETIC_CLASSES)
            bw = rng.uniform(0.08, 0.5) * width
            bh = rng.uniform(0.08, 0.6) * height
            x1 = rng.uniform(0, width - bw)
            y1 = rng.uniform(0, height - bh)
            conf = round(rng.uniform(0.05, 0.99), 4)
            if conf < confidence:
                continue
            detections.append({
                "class_id": cls["class_id"],
                "class_name": cls["label"],
                "confidence": conf,
                "box": [round(x1, 2), round(y1, 2),
                        round(x1 + bw, 2), round(y1 + bh, 2)],
            })
        detections.sort(key=lambda d: (-d["confidence"], d["class_id"]))
        out: dict[str, Any] = {"detections": detections}
        if include_native:
            out["native"] = {"adapter": "synthetic", "inference_ms": latency}
        return out


class EngineRegistry:
    """Factory/registry of installed engine adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, EngineAdapter] = {}
        self.errors: list[str] = []

    def register(self, adapter: EngineAdapter) -> None:
        self._adapters[adapter.engine_id] = adapter

    def get(self, engine_id: str) -> EngineAdapter | None:
        return self._adapters.get(engine_id)

    def all(self) -> list[EngineAdapter]:
        return list(self._adapters.values())

    def __contains__(self, engine_id: str) -> bool:
        return engine_id in self._adapters


ENGINE_REGISTRY = EngineRegistry()
ENGINE_REGISTRY.register(SyntheticAdapter())


def load_plugin_adapters(registry: EngineRegistry = ENGINE_REGISTRY) -> None:
    """Optional plugin hook: register adapters from 'opal_look.engines' entry
    points. Load failures are recorded for EngineDiscovery.errors."""
    import logging
    from importlib.metadata import entry_points

    for ep in entry_points(group="opal_look.engines"):
        try:
            registry.register(ep.load()())
        except Exception as exc:
            registry.errors.append(f"{ep.name}: {exc}")
            logging.getLogger(__name__).warning("failed to load engine plugin %s", ep.name)


def ensure_engines(store: Store, registry: EngineRegistry = ENGINE_REGISTRY) -> None:
    """Seed registry rows for installed adapters; idempotent."""
    with store.write_txn():
        for adapter in registry.all():
            store.engines.seed(adapter.engine_id, adapter.name, adapter.execution)


def engine_gate(store: Store, adapter: EngineAdapter) -> None:
    """Disabled/unavailable engines cannot serve inference (503)."""
    from .errors import ApiError

    row = store.engines.get(adapter.engine_id)
    if row is None:
        raise ApiError(503, f"Engine {adapter.engine_id!r} is not installed.")
    enabled = bool(row["enabled"])
    available, message = adapter.probe(json.loads(row["config"]), enabled)
    if not available:
        raise ApiError(503, f"Engine {adapter.engine_id!r} is unavailable: "
                            f"{message or 'disabled'}.")


def engine_runtime(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    """Internal rich engine view (probe, config, capabilities) for services."""
    adapter = ENGINE_REGISTRY.get(row["engine_id"])
    config = json.loads(row["config"])
    enabled = bool(row["enabled"])
    available, message = adapter.probe(config, enabled)
    return {
        "engine_id": row["engine_id"],
        "name": row["name"],
        "execution": row["execution"],
        "enabled": enabled,
        "available": available,
        "message": message,
        "capabilities": adapter.capabilities(),
        "config": config,
        "metadata": adapter.metadata(),
    }


def engine_read(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    """Kernel OpalEngine resource shape."""
    adapter = ENGINE_REGISTRY.get(row["engine_id"])
    config = json.loads(row["config"])
    enabled = bool(row["enabled"])
    available, _ = adapter.probe(config, enabled)
    capabilities = adapter.capabilities()
    metadata = adapter.metadata()
    return {
        "engine_id": row["engine_id"],
        "name": row["name"],
        "description": metadata.get("description"),
        "enabled": enabled,
        "available": available,
        "options": config,
        "metadata": metadata,
        "version": str(metadata.get("version", "0.0.0")),
        "state": "disabled" if not enabled else ("ready" if available else "unavailable"),
        "tasks": [{"task": t} for t in capabilities.get("tasks", [])],
        "device_types": list(capabilities.get("device_types", [])),
        "options_schema": adapter.options_schema(),
    }




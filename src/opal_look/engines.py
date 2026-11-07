"""Engine adapter registry.

Engines are installed/discovered by the implementation and advertised via
/api/v1/engines/. The built-in ``synthetic`` adapter produces deterministic,
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


def _rle_rect(width: int, height: int, box: dict[str, float]) -> dict[str, Any]:
    """Row-major RLE mask for a normalized rectangle at frame dimensions.

    Alternating background/foreground runs; first run is background (may
    be 0); sum(counts) == width*height.
    """
    x0 = int(box["x"] * width)
    y0 = int(box["y"] * height)
    x1 = min(width, x0 + max(1, int(box["width"] * width)))
    y1 = min(height, y0 + max(1, int(box["height"] * height)))

    counts: list[int] = []
    run = 0
    prev_fg = False

    def emit(length: int, fg: bool) -> None:
        nonlocal run, prev_fg
        if length == 0:
            return
        if fg == prev_fg:
            run += length
        else:
            counts.append(run)
            prev_fg = fg
            run = length

    for y in range(height):
        if y0 <= y < y1:
            emit(x0, False)
            emit(x1 - x0, True)
            emit(width - x1, False)
        else:
            emit(width, False)
    counts.append(run)
    return {"width": width, "height": height, "encoding": "rle", "counts": counts}

TASKS = ["detection", "classification", "segmentation", "pose", "ocr"]
SOURCE_TYPES = ["camera", "rtsp", "http", "host_video", "media"]

_SYNTHETIC_CLASSES = [
    {"class_id": 0, "label": "person"},
    {"class_id": 1, "label": "car"},
    {"class_id": 2, "label": "dog"},
]
_COCO_KEYPOINTS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
_SYNTHETIC_SKELETON = [
    [0, 1], [0, 2], [1, 3], [2, 4], [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
    [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
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
    def describe_model(self, resource: dict[str, Any]) -> dict[str, Any]: ...
    def validate_model(self, resource: dict[str, Any]) -> tuple[list[str], list[str]]: ...
    def validate_engine_options(self, options: dict[str, Any]) -> list[str]: ...
    def infer(
        self,
        width: int,
        height: int,
        task: str,
        model_desc: dict[str, Any],
        engine_options: dict[str, Any],
        frame_key: int,
    ) -> dict[str, Any]: ...


class SyntheticAdapter:
    """Deterministic built-in engine for development and contract tests."""

    engine_id = "synthetic"
    name = "Synthetic deterministic engine"
    execution = "local"

    _CONFIG_KEYS = {"seed", "force_unavailable"}

    def capabilities(self) -> dict[str, Any]:
        return {
            "tasks": list(TASKS),
            "tracking": True,
            "device_types": ["cpu"],
            "source_types": list(SOURCE_TYPES),
            "max_concurrent_sessions": None,
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

    def describe_model(self, resource: dict[str, Any]) -> dict[str, Any]:
        return {
            "tasks": list(TASKS),
            "tracking": True,
            "classes": list(_SYNTHETIC_CLASSES),
            "keypoints": [{"index": i, "name": n} for i, n in enumerate(_COCO_KEYPOINTS)],
            "skeleton": [list(edge) for edge in _SYNTHETIC_SKELETON],
            "metadata": {
                "adapter": "synthetic",
                "segmentation_kinds": ["instance", "semantic"],
                "ocr_languages": ["eng"],
            },
        }

    def validate_model(self, resource: dict[str, Any]) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        if not resource:
            errors.append("resource locator must be a non-empty object")
        unknown = set(resource) - {"path", "ref"}
        for key in sorted(unknown):
            warnings.append(f"unrecognized resource key: {key}")
        return errors, warnings

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

    def infer(
        self,
        width: int,
        height: int,
        task: str,
        model_desc: dict[str, Any],
        engine_options: dict[str, Any],
        frame_key: int,
    ) -> dict[str, Any]:
        if engine_options.get("fail"):
            raise EngineUnavailable("synthetic engine forced failure")
        latency = engine_options.get("latency_ms") or 0
        if latency:
            import time

            time.sleep(min(latency, 10_000) / 1000)
        rng = random.Random((engine_options.get("seed") or 0) ^ frame_key ^ hash(task))
        classes = model_desc["classes"]

        def box() -> dict[str, float]:
            w = round(rng.uniform(0.08, 0.5), 4)
            h = round(rng.uniform(0.08, 0.6), 4)
            return {
                "x": round(rng.uniform(0, 1 - w), 4),
                "y": round(rng.uniform(0, 1 - h), 4),
                "width": w,
                "height": h,
            }

        def pick() -> dict[str, Any]:
            cls = rng.choice(classes)
            return {
                "class_id": cls["class_id"],
                "label": cls["label"],
                "confidence": round(rng.uniform(0.05, 0.99), 4),
            }

        n = rng.randint(1, 3)
        if task == "detection":
            objects = [
                {**pick(), "box": box(), "track_id": None} for _ in range(n)
            ]
            objects.sort(key=lambda o: (-o["confidence"], o["class_id"], o["box"]["x"], o["box"]["y"]))
            return {"task": "detection", "objects": objects}
        if task == "classification":
            scored = [pick() for _ in classes]
            scored.sort(key=lambda c: (-c["confidence"], c["class_id"]))
            return {"task": "classification", "classes": scored}
        if task == "segmentation":
            if engine_options.get("segmentation_kind", "instance") == "semantic":
                half = (width * height) // 2
                return {
                    "task": "segmentation",
                    "kind": "semantic",
                    "map": {
                        "width": width,
                        "height": height,
                        "encoding": "rle",
                        "runs": [
                            {"class_id": classes[0]["class_id"], "count": half},
                            {"class_id": classes[1]["class_id"], "count": width * height - half},
                        ],
                        "classes": [
                            {"class_id": classes[0]["class_id"], "label": classes[0]["label"], "confidence": 0.9},
                            {"class_id": classes[1]["class_id"], "label": classes[1]["label"], "confidence": 0.8},
                        ],
                    },
                }
            instances = [
                {**pick(), "box": b, "mask": _rle_rect(width, height, b)}
                for b in (box() for _ in range(n))
            ]
            instances.sort(key=lambda o: (-o["confidence"], o["class_id"], o["box"]["x"], o["box"]["y"]))
            return {"task": "segmentation", "kind": "instance", "instances": instances}
        if task == "pose":
            poses = []
            for _ in range(n):
                base = pick()
                keypoints = [
                    {
                        "index": kp["index"],
                        "x": round(rng.random(), 4),
                        "y": round(rng.random(), 4),
                        "confidence": round(rng.uniform(0.3, 0.99), 4),
                    }
                    for kp in model_desc["keypoints"]
                ]
                poses.append({**base, "box": box(), "keypoints": keypoints})
            poses.sort(key=lambda o: (-o["confidence"], o["class_id"], o["box"]["x"], o["box"]["y"]))
            return {"task": "pose", "poses": poses}
        if task == "ocr":
            regions = [
                {
                    "text": rng.choice(["OPAL LOOK", "SNAPSHOT 42", "EXIT", "ZONE A"]),
                    "confidence": round(rng.uniform(0.4, 0.99), 4),
                    "polygon": [
                        {"x": round(bx, 4), "y": round(by, 4)}
                        for bx, by in (
                            (0.1, 0.1), (0.4, 0.1), (0.4, 0.2), (0.1, 0.2)
                        )
                    ],
                    "language": "eng",
                }
                for _ in range(n)
            ]
            return {"task": "ocr", "regions": regions}
        raise ValueError(f"unsupported task: {task}")


class EngineRegistry:
    """Factory/registry of installed engine adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, EngineAdapter] = {}

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
    """Optional plugin hook: register adapters from 'opal_look.engines' entry points."""
    import logging
    from importlib.metadata import entry_points

    for ep in entry_points(group="opal_look.engines"):
        try:
            registry.register(ep.load()())
        except Exception:
            logging.getLogger(__name__).warning("failed to load engine plugin %s", ep.name)


def ensure_engines(store: Store, registry: EngineRegistry = ENGINE_REGISTRY) -> None:
    """Seed registry rows for installed adapters; idempotent."""
    with store.write_txn():
        for adapter in registry.all():
            store.engines.seed(adapter.engine_id, adapter.name, adapter.execution)


def ensure_default_model(store: Store) -> None:
    """Seed one usable synthetic model so the service is ready out of the box."""
    with store.write_txn():
        store.models.seed(
            "synthetic-vision",
            "Synthetic vision model",
            "synthetic",
            {"ref": "builtin"},
        )


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


def model_runtime(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    """Internal rich model view (adapter description + availability)."""
    adapter = ENGINE_REGISTRY.get(row["engine_id"])
    engine_row = store.engines.get(row["engine_id"])
    config = json.loads(engine_row["config"])
    engine_enabled = bool(engine_row["enabled"])
    engine_available, _ = adapter.probe(config, engine_enabled)
    description = adapter.describe_model(json.loads(row["resource"]))
    enabled = bool(row["enabled"])
    return {
        "model_id": row["model_id"],
        "name": row["name"],
        "engine_id": row["engine_id"],
        "resource": json.loads(row["resource"]),
        "enabled": enabled,
        "available": enabled and engine_enabled and engine_available,
        "tasks": description["tasks"],
        "tracking": description["tracking"],
        "classes": description["classes"],
        "keypoints": description["keypoints"],
        "skeleton": description["skeleton"],
        "metadata": description["metadata"],
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


def model_read(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    """Contract Model resource (v1.5 shape)."""
    adapter = ENGINE_REGISTRY.get(row["engine_id"])
    engine_row = store.engines.get(row["engine_id"])
    engine_enabled = bool(engine_row["enabled"]) if engine_row is not None else False
    engine_available = False
    if adapter is not None and engine_row is not None:
        engine_available, _ = adapter.probe(json.loads(engine_row["config"]), engine_enabled)
    enabled = bool(row["enabled"])
    declared = json.loads(row["tasks"]) if row["tasks"] else []
    if not declared and adapter is not None:
        declared = adapter.describe_model(json.loads(row["resource"]))["tasks"]
    return {
        "id": row["model_id"],
        "engine_id": row["engine_id"],
        "display_name": row["name"],
        "tasks": declared,
        "state": (
            "disabled" if not enabled
            else "unavailable" if not engine_available
            else "ready"
        ),
        "resource_label": row["resource_ref"],
        "created_at": row["created_at"],
    }

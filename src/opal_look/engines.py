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
import sqlite3
from typing import Any, Protocol

from .store import Store

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
    def validate_config(self, config: dict[str, Any]) -> list[str]: ...
    def metadata(self) -> dict[str, Any]: ...
    def describe_model(self, resource: dict[str, Any]) -> dict[str, Any]: ...
    def validate_model(self, resource: dict[str, Any]) -> tuple[list[str], list[str]]: ...


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
            "source_types": list(SOURCE_TYPES),
            "max_concurrent_sessions": None,
        }

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


ADAPTERS: dict[str, EngineAdapter] = {a.engine_id: a for a in (SyntheticAdapter(),)}


def ensure_engines(store: Store) -> None:
    """Seed registry rows for installed adapters; idempotent."""
    with store.write_txn():
        for adapter in ADAPTERS.values():
            store._conn.execute(
                "INSERT OR IGNORE INTO engines (engine_id, name, execution, enabled, config, metadata) "
                "VALUES (?, ?, ?, 1, '{}', '{}')",
                (adapter.engine_id, adapter.name, adapter.execution),
            )


def ensure_default_model(store: Store) -> None:
    """Seed one usable synthetic model so the service is ready out of the box."""
    with store.write_txn():
        store._conn.execute(
            "INSERT OR IGNORE INTO models (model_id, name, engine_id, resource, enabled) "
            "VALUES ('synthetic-vision', 'Synthetic vision model', 'synthetic', ?, 1)",
            ('{"ref": "builtin"}',),
        )


def engine_read(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    adapter = ADAPTERS[row["engine_id"]]
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


def model_read(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    adapter = ADAPTERS[row["engine_id"]]
    engine_row = store.get_engine(row["engine_id"])
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

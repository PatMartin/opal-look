"""Profile resolution and task/settings compatibility validation."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .engines import ENGINE_REGISTRY, model_runtime
from .schemas import AnalysisSettings
from .store import Store


def resolve_settings(task: str, supplied: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults materialized, supplied fields replace; segmentation_kind is
    omitted for non-segmentation tasks."""
    resolved = AnalysisSettings().model_dump(mode="json")
    if supplied:
        resolved.update(supplied)
    if task != "segmentation":
        resolved.pop("segmentation_kind", None)
    return resolved


def supplied_settings_keys(settings_obj: Any) -> dict[str, Any]:
    """Dump only explicitly-supplied fields of an AnalysisSettings model."""
    if settings_obj is None:
        return {}
    return settings_obj.model_dump(exclude_unset=True)


def profile_errors(
    store: Store,
    model_row: sqlite3.Row,
    task: str,
    supplied: dict[str, Any],
    resolved: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors cover task/setting incompatibility;
    warnings cover current runtime unavailability."""
    errors: list[str] = []
    warnings: list[str] = []
    read = model_runtime(store, model_row)
    adapter = ENGINE_REGISTRY.get(read["engine_id"])

    if not read["enabled"]:
        errors.append(f"model {read['model_id']!r} is disabled")
    if task not in read["tasks"]:
        errors.append(f"task {task!r} is not supported by model {read['model_id']!r}")
    elif not read["available"]:
        warnings.append(f"model {read['model_id']!r} is currently unavailable")

    # Controls irrelevant to the task must be omitted (checked on supplied).
    if task != "detection" and "tracking" in supplied:
        errors.append("tracking is only valid for detection tasks")
    if task != "segmentation" and "segmentation_kind" in supplied:
        errors.append("segmentation_kind is only valid for segmentation tasks")
    # Value-level checks on the resolved settings.
    if task == "ocr" and resolved.get("class_labels"):
        errors.append("class label filters are invalid for ocr tasks")
    model_labels = {cls["label"] for cls in read["classes"]}
    for label in resolved.get("class_labels") or []:
        if label not in model_labels:
            errors.append(f"unknown class label for model: {label!r}")
    if resolved.get("tracking") and not read["tracking"]:
        errors.append("model/engine do not advertise tracking")
    if adapter is not None:
        errors += adapter.validate_engine_options(resolved.get("engine_options") or {})
    return errors, warnings


def profile_read(row: sqlite3.Row) -> dict[str, Any]:
    """Kernel OpalProfile: opaque fields persisted verbatim in `data`."""
    data = json.loads(row["data"] or "{}") if "data" in row.keys() else {}
    return {
        "id": row["profile_id"],
        "name": row["name"],
        "is_active": bool(row["active"]),
        **data,
    }

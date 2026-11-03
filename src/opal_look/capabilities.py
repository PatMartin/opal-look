"""GET /api/v1/capabilities/: catalog built from registered adapters,
models, capture adapters and effective settings — never hard-coded.

Optional arrays/flags are omitted when the capability is genuinely absent,
so clients can distinguish "not offered" from "offered but empty".
"""

from __future__ import annotations

from typing import Any

from .capture import CAPTURE_REGISTRY
from .constants import IMAGE_CONTENT_TYPES
from .engines import ENGINE_REGISTRY, model_runtime
from .settings import effective_settings
from .store import Store

# Task -> declared output payload kinds produced by the synthetic engine.
_TASK_OUTPUTS = {
    "detection": ["boxes", "classes"],
    "classification": ["labels"],
    "segmentation": ["masks", "boxes"],
    "pose": ["keypoints", "skeleton"],
    "ocr": ["text", "boxes"],
}

# Presentation filters actually implemented by analysis.apply_filters.
_PORTABLE_FILTERS = [
    "grayscale", "brightness_contrast", "blur", "sharpen", "threshold",
    "edges", "rotate", "flip", "crop", "resize", "motion",
]


def _task_descriptors(store: Store) -> list[dict[str, Any]]:
    """One CapabilityDescriptor per enabled task on any enabled model."""
    seen: dict[str, dict[str, Any]] = {}
    for row in store.models.list(enabled=True):
        runtime = model_runtime(store, row)
        if not runtime["available"]:
            continue
        for task in runtime["tasks"]:
            desc = seen.setdefault(task, {
                "task": task,
                "supported_inputs": ["image", "source_frame"],
                "output_types": list(_TASK_OUTPUTS.get(task, ["observations"])),
            })
            if runtime["tracking"]:
                desc["supports_tracking"] = True
    return [seen[t] for t in sorted(seen)]


def _source_kinds(store: Store) -> list[str]:
    kinds = {"media"}  # uploaded media input always works
    for adapter in CAPTURE_REGISTRY.all():
        installed, _ = adapter.installed()
        if installed:
            kinds.add(adapter.source_type)
    return sorted(kinds)


def _stream_transports(store: Store) -> list[str]:
    transports = []
    for adapter in CAPTURE_REGISTRY.all():
        installed, _ = adapter.installed()
        if installed and adapter.source_type == "rtsp":
            transports.append("rtsp")
    return transports


def capability_catalog(store: Store) -> dict[str, Any]:
    settings = effective_settings(store)
    catalog: dict[str, Any] = {
        "tasks": _task_descriptors(store),
        "source_kinds": _source_kinds(store),
        "media_types": list(IMAGE_CONTENT_TYPES),
        "stream_transports": _stream_transports(store),
        "export_formats": ["json"],
        "limits": {
            "max_upload_bytes": settings.max_upload_bytes,
            "max_image_pixels": settings.max_image_pixels,
            "max_concurrent_sessions": settings.max_concurrent_sessions,
            "result_retention_hours": settings.result_retention_hours,
        },
        "filters": list(_PORTABLE_FILTERS),
        "supports_raw_stream": False,
        "supports_motion_gate": False,
        "supports_recording": False,
        "supports_monitoring": False,
        "supports_finite_video_analysis": False,
        "supports_remote_inference": False,
    }
    return catalog

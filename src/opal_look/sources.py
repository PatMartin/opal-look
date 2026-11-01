"""Source-type adapters: locator validation, capability probing, live flags.

Registration is configuration only; availability reflects current observed
status (no forced network/device probes on reads). Capture adapters land
with session support; until then non-file sources report unavailable.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any

from .refs import media_exists
from .store import Store

LIVE_TYPES = {"camera", "rtsp", "http"}
FINITE_TYPES = {"host_video", "media"}

# Adapter-known source_options keys per type; unknown keys are rejected.
SOURCE_OPTION_KEYS: dict[str, frozenset[str]] = {
    "camera": frozenset({"width", "height", "fps", "backend"}),
    "rtsp": frozenset({"transport", "timeout_ms"}),
    "http": frozenset({"timeout_ms"}),
    "host_video": frozenset(),
    "media": frozenset(),
}

_URL_CREDENTIALS = re.compile(r"^[a-z][a-z0-9+.-]*://[^/@\s]+@", re.IGNORECASE)


def check_locator(source_type: str, locator: str) -> list[str]:
    """Structural locator checks (422-level errors)."""
    if _URL_CREDENTIALS.match(locator):
        return ["locator must not contain inline credentials"]
    if source_type == "camera":
        if "://" in locator:
            return ["camera locator must be a discovered device_id, not a URL"]
    elif source_type == "rtsp":
        if not locator.lower().startswith("rtsp://"):
            return ["rtsp locator must be an rtsp:// URL"]
    elif source_type == "http":
        if not locator.lower().startswith(("http://", "https://")):
            return ["http locator must be an http(s):// URL"]
    elif source_type == "media":
        from .schemas import IDENTIFIER_PATTERN

        if not re.match(IDENTIFIER_PATTERN, locator):
            return ["media locator must be an uploaded media_id"]
    return []


def check_source_options(source_type: str, options: dict[str, Any]) -> list[str]:
    unknown = sorted(set(options) - SOURCE_OPTION_KEYS[source_type])
    return [f"unknown source option: {key}" for key in unknown]


def missing_reference(store: Store, source_type: str, locator: str) -> str | None:
    """Referenced-resource check (-> 404)."""
    if source_type == "media" and not media_exists(store, locator):
        return f"unknown media: {locator!r}"
    return None


def probe(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    """Observed availability probe; does not open network/device resources."""
    source_type = row["type"]
    locator = row["locator"]
    enabled = bool(row["enabled"])

    if not enabled:
        return _probe_result(False, "source disabled")
    if source_type == "camera":
        return _probe_result(False, "no camera capture adapter installed")
    if source_type in ("rtsp", "http"):
        return _probe_result(False, "network source not yet probed")
    if source_type == "host_video":
        if not os.path.isfile(locator):
            return _probe_result(False, "host path not found")
        return _probe_result(False, "no video decoder installed")
    if source_type == "media":
        if media_exists(store, locator):
            return _probe_result(True, None)
        return _probe_result(False, "referenced media is unavailable")
    return _probe_result(False, "unknown source type")


def _probe_result(available: bool, message: str | None) -> dict[str, Any]:
    return {
        "available": available,
        "message": message,
        "width": None,
        "height": None,
        "fps": None,
        "duration_ms": None,
    }


def source_read(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    probed = probe(store, row)
    return {
        "source_id": row["source_id"],
        "name": row["name"],
        "type": row["type"],
        "locator": row["locator"],
        "credential_ref": row["credential_ref"],
        "enabled": bool(row["enabled"]),
        "source_options": json.loads(row["source_options"]),
        "available": probed["available"],
        "live": row["type"] in LIVE_TYPES,
        "width": probed["width"],
        "height": probed["height"],
        "fps": probed["fps"],
        "duration_ms": probed["duration_ms"],
        "message": probed["message"],
    }


def validate_source(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    read = source_read(store, row)
    errors = check_locator(read["type"], read["locator"])
    errors += check_source_options(read["type"], read["source_options"])
    ref = missing_reference(store, read["type"], read["locator"])
    if ref:
        errors.append(ref)
    if not read["enabled"]:
        errors.append("source is disabled")
    elif not read["available"]:
        errors.append(f"source unavailable: {read['message'] or 'probe failed'}")
    warnings = []
    if read["type"] in ("rtsp", "http"):
        warnings.append("network source availability is not probed on read")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "details": {"type": read["type"], "live": read["live"]},
    }


def discover_cameras() -> list[dict[str, Any]]:
    """Installed capture-adapter camera enumeration; none installed yet."""
    return []

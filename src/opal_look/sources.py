"""Source-type adapters: locator validation, capability probing, live flags.

Registration is configuration only; availability reflects installed
capture adapters (no forced network/device probes on reads). Live
connectivity is checked explicitly via /validate for types with an
installed capture adapter.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any
from urllib.parse import urlsplit

from .refs import media_exists
from .store import Store

LIVE_TYPES = {"usb", "rtsp", "http_mjpeg", "adapter"}
FINITE_TYPES = {"file", "media", "image"}

# Adapter-known source_options keys per type; unknown keys are rejected.
SOURCE_OPTION_KEYS: dict[str, frozenset[str]] = {
    "camera": frozenset({"width", "height", "fps", "backend"}),
    "rtsp": frozenset({"transport", "timeout_ms"}),
    "http": frozenset({"timeout_ms"}),
    "file": frozenset(),
    "media": frozenset(),
    "image": frozenset(),
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
    elif source_type in ("file", "image"):
        if "://" in locator:
            return [f"{source_type} locator must be a host filesystem path, not a URL"]
    return []


def check_source_options(source_type: str, options: dict[str, Any]) -> list[str]:
    errors = [f"unknown source option: {key}"
              for key in sorted(set(options) - SOURCE_OPTION_KEYS[source_type])]
    if source_type == "rtsp":
        transport = options.get("transport")
        if transport is not None and transport not in ("tcp", "udp"):
            errors.append("source option 'transport' must be 'tcp' or 'udp'")
        timeout = options.get("timeout_ms")
        if timeout is not None and (
            not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0
        ):
            errors.append("source option 'timeout_ms' must be a positive integer")
    return errors


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
    if source_type == "rtsp":
        from .capture import capture_adapter_for

        adapter = capture_adapter_for("rtsp")
        if adapter is None:
            return _probe_result(False, "no rtsp capture adapter installed")
        installed, message = adapter.installed()
        return _probe_result(installed, message)
    if source_type == "http":
        return _probe_result(False, "network source not yet probed")
    if source_type == "file":
        if not os.path.isfile(locator):
            return _probe_result(False, "host path not found")
        return _probe_result(False, "no video decoder installed")
    if source_type == "image":
        if not os.path.isfile(locator):
            return _probe_result(False, "host path not found")
        try:
            from PIL import Image
            with Image.open(locator) as im:
                im.verify()
        except Exception:
            return _probe_result(False, "image file is not readable")
        return _probe_result(True, None)
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


def redact_locator(kind: str, locator: str) -> str:
    """Privacy redaction for locators on GET/export.

    userinfo cannot exist (rejected at write). URL kinds keep
    scheme://authority only (path/query can embed sensitive names);
    media keeps its opaque media_id (needed to fetch content);
    device/path locators are masked entirely.
    """
    if kind in ("rtsp", "http"):
        parts = urlsplit(locator)
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host += f":{parts.port}"
        return f"{parts.scheme}://{host}/…"
    if kind == "media":
        return locator
    return "…"


_LIVE_KINDS = frozenset({"rtsp", "http_mjpeg", "usb", "adapter"})


def _source_capabilities(kind: str) -> list[str]:
    """Contract Source.capabilities: honest per-kind operation tags."""
    if kind in _LIVE_KINDS:
        return ["probe", "status", "frame", "stream", "capture", "recording"]
    return ["frame", "capture"]


def source_read(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    """Contract Source resource (upstream v1.5 shape); locator redacted."""
    probed = probe(store, row)
    enabled = bool(row["enabled"])
    kind = row["type"]
    return {
        "id": row["source_id"],
        "kind": kind,
        "name": row["name"],
        "enabled": enabled,
        "state": (
            "disabled" if not enabled
            else "ready" if probed["available"]
            else "disconnected"
        ),
        "redacted_locator": redact_locator(kind, row["locator"]),
        "last_frame_at": None,
        "capabilities": _source_capabilities(kind),
    }


def validate_source(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    probed = probe(store, row)
    read = {
        "type": row["type"], "locator": row["locator"], "enabled": bool(row["enabled"]),
        "source_options": json.loads(row["source_options"]),
        "available": probed["available"], "live": row["type"] in LIVE_TYPES,
        "message": probed["message"], "credential_ref": row["credential_ref"],
    }
    errors = check_locator(read["type"], read["locator"])
    errors += check_source_options(read["type"], read["source_options"])
    ref = missing_reference(store, read["type"], read["locator"])
    if ref:
        errors.append(ref)
    if not read["enabled"]:
        errors.append("source is disabled")
    elif not read["available"]:
        errors.append(f"source unavailable: {read['message'] or 'probe failed'}")
    details = {"type": read["type"], "live": read["live"]}
    if read["type"] == "rtsp" and read["enabled"] and read["available"]:
        _validate_rtsp_connect(read, errors, details)
    warnings = []
    if read["type"] in ("rtsp", "http"):
        warnings.append("network source availability is not probed on read")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "details": details,
    }


def _validate_rtsp_connect(read: dict[str, Any], errors: list[str], details: dict) -> None:
    """Bounded live connectivity check for /validate (not run on reads)."""
    from .capture import CaptureError, capture_adapter_for, credentialed_locator

    adapter = capture_adapter_for("rtsp")
    if adapter is None:
        return
    try:
        url = credentialed_locator(read["locator"], read["credential_ref"])
    except CaptureError as exc:
        errors.append(str(exc))
        return
    probed = adapter.probe_stream(read["locator"], read["source_options"], url)
    if not probed["available"]:
        errors.append(f"stream unreachable: {probed['message'] or 'connect failed'}")
        return
    details.update(
        {"width": probed["width"], "height": probed["height"], "fps": probed["fps"]})


def discover_cameras() -> list[dict[str, Any]]:
    """Installed capture-adapter camera enumeration; none installed yet."""
    return []

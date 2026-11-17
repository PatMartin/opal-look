"""OPAL_LOOK_ENGINE_YOLO_* environment wiring.

BASE_URL presence registers the remote adapter. Values are seeded into the
engines table at startup and are authoritative over PATCH changes (same rule
as OPAL_LOOK_<SETTING>). TOKEN is read per-request and never stored.
"""

from __future__ import annotations

import os
from typing import Any

ENV_PREFIX = "OPAL_LOOK_ENGINE_YOLO_"
ENGINE_ID = "yolo"

_TRUE = {"1", "true", "yes", "on"}


def _get(key: str) -> str | None:
    value = os.environ.get(ENV_PREFIX + key)
    if value is None:
        return None
    value = value.strip()
    return value or None


def env_base_url() -> str | None:
    return _get("BASE_URL")


def env_enabled() -> bool | None:
    """True/False when ENABLED is set, None when unset (leave seeded flag)."""
    raw = _get("ENABLED")
    return None if raw is None else raw.lower() in _TRUE


def env_token() -> str | None:
    return _get("TOKEN")


def env_config() -> dict[str, Any]:
    """Config dict mirrored into engines.config (validated keys only)."""
    config: dict[str, Any] = {}
    if url := env_base_url():
        config["base_url"] = url
    if raw := _get("TIMEOUT_SECONDS"):
        try:
            config["timeout_seconds"] = float(raw)
        except ValueError:
            pass
    return config

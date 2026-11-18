"""Portable service settings: schema, defaults, patch model, resolution."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .store import Store


class ServiceSettings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    frame_cache_seconds: int = Field(default=30, ge=1)
    sse_replay_seconds: int = Field(default=60, ge=1)
    sse_buffer_events: int = Field(default=256, ge=1)
    max_concurrent_streams: int = Field(default=4, ge=1)
    max_upload_bytes: int = Field(default=1_073_741_824, ge=1)
    max_image_pixels: int = Field(default=50_000_000, ge=1)
    max_viewers: int = Field(default=8, ge=1)
    # Outbound source policy (opal_look.source_policy).
    source_local_roots: list[str] = Field(default_factory=list)
    source_allowed_hosts: list[str] = Field(default_factory=list)
    source_allow_private: bool = False


class ServiceSettingsPatch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    frame_cache_seconds: int | None = Field(default=None, ge=1)
    sse_replay_seconds: int | None = Field(default=None, ge=1)
    sse_buffer_events: int | None = Field(default=None, ge=1)
    max_concurrent_streams: int | None = Field(default=None, ge=1)
    max_upload_bytes: int | None = Field(default=None, ge=1)
    max_image_pixels: int | None = Field(default=None, ge=1)
    max_viewers: int | None = Field(default=None, ge=1)
    source_local_roots: list[str] | None = Field(default=None)
    source_allowed_hosts: list[str] | None = Field(default=None)
    source_allow_private: bool | None = Field(default=None)


class SingleSettingPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any


SETTINGS_KEYS = frozenset(ServiceSettings.model_fields)


def effective_settings(store: Store) -> ServiceSettings:
    overrides = store.settings.overrides()
    return ServiceSettings.model_validate(
        {k: v for k, v in overrides.items() if k in SETTINGS_KEYS}
    )


ENV_PREFIX = "OPAL_LOOK_"
_log = logging.getLogger(__name__)


def env_setting_overrides(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """OPAL_LOOK_<SETTING_KEY> environment variables -> validated overrides.

    Only names matching a documented setting key apply; other OPAL_LOOK_*
    vars (HOST/PORT/TOKEN/CRED_*) are ignored. Values are parsed as JSON
    first, then as a raw string; anything failing schema validation is
    skipped with a warning rather than blocking startup.
    """
    env = os.environ if environ is None else environ
    out: dict[str, Any] = {}
    for var, raw in env.items():
        if not var.startswith(ENV_PREFIX):
            continue
        key = var[len(ENV_PREFIX):].lower()
        if key not in SETTINGS_KEYS:
            continue
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            value = raw
        try:
            validated = ServiceSettingsPatch.model_validate({key: value})
        except ValidationError:
            _log.warning("ignoring %s=%r: invalid value for setting %r",
                         var, raw, key)
            continue
        out[key] = validated.model_dump(exclude_unset=True)[key]
    return out


def apply_env_settings(store: Store,
                       environ: dict[str, str] | None = None) -> list[str]:
    """Seed ``setting_overrides`` from OPAL_LOOK_<key> env vars.

    The environment is authoritative: a defined key is (re)written each
    startup, superseding API-set overrides. Keys whose stored value already
    matches are skipped. Returns the keys that changed; the config revision
    is bumped only when at least one did.
    """
    desired = env_setting_overrides(environ)
    changed = [
        key for key, value in desired.items()
        if (entry := store.settings.entry(key)) is None
        or entry["value"] != value
    ]
    if not changed:
        return []
    with store.write_txn():
        for key in changed:
            store.settings.set(key, desired[key])
        store.bump_revision()
    _log.info("applied setting(s) from environment: %s",
              ", ".join(sorted(changed)))
    return changed

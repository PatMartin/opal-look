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
    """Effective values: persisted overrides under environment/.env overlays
    (precedence environment > dotenv > persisted > default)."""
    overrides = dict(store.settings.overrides())
    for key, overlay in env_overlays().items():
        overrides[key] = overlay["value"]
    return ServiceSettings.model_validate(
        {k: v for k, v in overrides.items() if k in SETTINGS_KEYS}
    )


ENV_PREFIX = "OPAL_LOOK_"
DOTENV_FILE_VAR = "OPAL_DOTENV_FILE"
NO_DOTENV_VAR = "OPAL_NO_DOTENV"
_INVALID = object()
_log = logging.getLogger(__name__)


def _parse_setting(key: str, raw: Any) -> Any:
    """JSON-then-string parse + schema validation for one setting value."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        value = raw
    try:
        validated = ServiceSettingsPatch.model_validate({key: value})
    except ValidationError:
        return _INVALID
    return validated.model_dump(exclude_unset=True)[key]


def env_setting_overrides(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """OPAL_LOOK_<SETTING_KEY> variables -> validated values.

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
        value = _parse_setting(key, raw)
        if value is _INVALID:
            _log.warning("ignoring %s=%r: invalid value for setting %r",
                         var, raw, key)
            continue
        out[key] = value
    return out


def _dotenv_setting_keys(environ: dict[str, str]) -> set[str]:
    """Setting keys whose process value was sourced from the dotenv file.

    Only counts when dotenv prepare() recorded ``OPAL_DOTENV_FILE``; a file
    var only sourced the process value when the real environment did not
    already define it (``load_dotenv(override=False)``).
    """
    path = environ.get(DOTENV_FILE_VAR)
    if not path or environ.get(NO_DOTENV_VAR):
        return set()
    from dotenv import dotenv_values
    try:
        file_vars = dotenv_values(path)
    except OSError:
        return set()
    keys = set()
    for var, value in file_vars.items():
        if not isinstance(var, str) or not var.startswith(ENV_PREFIX):
            continue
        key = var[len(ENV_PREFIX):].lower()
        if key not in SETTINGS_KEYS or value is None:
            continue
        if environ.get(var) == value:
            keys.add(key)
    return keys


def env_overlays(environ: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """{key: {"value", "source"}} for env/dotenv-supplied setting values.

    ``source`` is ``environment`` for real environment variables and
    ``dotenv`` for values that came from the loaded dotenv file.
    """
    env = os.environ if environ is None else environ
    dotenv_keys = _dotenv_setting_keys(env)
    return {
        key: {"value": value,
              "source": "dotenv" if key in dotenv_keys else "environment"}
        for key, value in env_setting_overrides(env).items()
    }

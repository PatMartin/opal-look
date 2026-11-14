"""Portable service settings: schema, defaults, patch model, resolution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class ServiceSettingsPatch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    frame_cache_seconds: int | None = Field(default=None, ge=1)
    sse_replay_seconds: int | None = Field(default=None, ge=1)
    sse_buffer_events: int | None = Field(default=None, ge=1)
    max_concurrent_streams: int | None = Field(default=None, ge=1)
    max_upload_bytes: int | None = Field(default=None, ge=1)
    max_image_pixels: int | None = Field(default=None, ge=1)
    max_viewers: int | None = Field(default=None, ge=1)


class SingleSettingPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any


SETTINGS_KEYS = frozenset(ServiceSettings.model_fields)


def effective_settings(store: Store) -> ServiceSettings:
    return ServiceSettings.model_validate(store.settings.overrides())

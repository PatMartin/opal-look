"""Portable service settings: schema, defaults, patch model, resolution."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import Store

EVENT_TOPICS = (
    "opal.look.session.started",
    "opal.look.session.completed",
    "opal.look.session.failed",
    "opal.look.analysis.completed",
)
Topic = Literal[
    "opal.look.session.started",
    "opal.look.session.completed",
    "opal.look.session.failed",
    "opal.look.analysis.completed",
]


class ServiceSettings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    result_retention_hours: int = Field(default=168, ge=1)
    media_retention_hours: int = Field(default=24, ge=1)
    snapshot_retention_hours: int = Field(default=168, ge=1)
    frame_cache_seconds: int = Field(default=30, ge=1)
    sse_replay_seconds: int = Field(default=60, ge=1)
    sse_buffer_events: int = Field(default=256, ge=1)
    max_concurrent_sessions: int = Field(default=4, ge=1)
    max_upload_bytes: int = Field(default=1_073_741_824, ge=1)
    max_image_pixels: int = Field(default=50_000_000, ge=1)
    max_analysis_timeout_seconds: int = Field(default=60, ge=1)
    max_preview_fps: float = Field(default=5, gt=0)
    max_result_query_limit: int = Field(default=1000, ge=1)
    events_enabled: bool = Field(default=False)
    event_topics_allowlist: list[Topic] = Field(default_factory=lambda: list(EVENT_TOPICS))
    max_analysis_events_per_second: float = Field(default=5, gt=0)
    event_queue_capacity: int = Field(default=256, ge=1)
    max_viewers: int = Field(default=8, ge=1)
    default_pipeline_id: str | None = Field(default=None)

    @field_validator("event_topics_allowlist")
    @classmethod
    def _unique_topics(cls, topics: list[str]) -> list[str]:
        if len(set(topics)) != len(topics):
            raise ValueError("event_topics_allowlist entries must be unique")
        return topics


class ServiceSettingsPatch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    result_retention_hours: int | None = Field(default=None, ge=1)
    media_retention_hours: int | None = Field(default=None, ge=1)
    snapshot_retention_hours: int | None = Field(default=None, ge=1)
    frame_cache_seconds: int | None = Field(default=None, ge=1)
    sse_replay_seconds: int | None = Field(default=None, ge=1)
    sse_buffer_events: int | None = Field(default=None, ge=1)
    max_concurrent_sessions: int | None = Field(default=None, ge=1)
    max_upload_bytes: int | None = Field(default=None, ge=1)
    max_image_pixels: int | None = Field(default=None, ge=1)
    max_analysis_timeout_seconds: int | None = Field(default=None, ge=1)
    max_preview_fps: float | None = Field(default=None, gt=0)
    max_result_query_limit: int | None = Field(default=None, ge=1)
    events_enabled: bool | None = Field(default=None)
    event_topics_allowlist: list[Topic] | None = Field(default=None)
    max_analysis_events_per_second: float | None = Field(default=None, gt=0)
    event_queue_capacity: int | None = Field(default=None, ge=1)
    max_viewers: int | None = Field(default=None, ge=1)
    default_pipeline_id: str | None = Field(default=None)

    @field_validator("event_topics_allowlist")
    @classmethod
    def _unique_topics(cls, topics: list[str] | None) -> list[str] | None:
        if topics is not None and len(set(topics)) != len(topics):
            raise ValueError("event_topics_allowlist entries must be unique")
        return topics


class SingleSettingPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any


SETTINGS_KEYS = frozenset(ServiceSettings.model_fields)


def effective_settings(store: Store) -> ServiceSettings:
    return ServiceSettings.model_validate(store.settings.overrides())

"""Pydantic DTOs shared across routers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import ApiError

IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"


def reject_null_fields(supplied: dict[str, Any]) -> None:
    """Explicit null is not a valid value for non-nullable patch fields."""
    if any(value is None for value in supplied.values()):
        raise ApiError(422, "Explicit null values are not allowed in updates.")


class EnginePatch(BaseModel):
    """enabled and/or engine options (validated by adapter)."""
    model_config = ConfigDict(strict=True, extra="forbid")

    enabled: bool | None = Field(default=None)
    options: dict[str, Any] | None = Field(default=None)


class PredictRequest(BaseModel):
    """Single-image inference request (engine required)."""
    model_config = ConfigDict(extra="forbid")

    engine_id: str = Field(min_length=1)
    model_id: str
    source: str = Field(min_length=1)
    confidence: float = Field(default=0.25, ge=0.0, le=1.0)
    device_id: str | None = None
    engine_options: dict[str, Any] = Field(default_factory=dict)
    include_native: bool = False


class StreamStartRequest(BaseModel):
    """Ephemeral RTSP stream admission (engine-free video or inference)."""
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=8, pattern=r"^rtsps?://")
    engine_id: str | None = None
    model_id: str | None = None
    confidence: float = Field(default=0.25, ge=0.0, le=1.0)
    device_id: str | None = None
    engine_options: dict[str, Any] | None = None
    annotate: bool = False
    buffer_policy: Literal["drop-oldest", "drop-newest", "block"] = "drop-oldest"
    buffer_size: int = Field(default=5, ge=1, le=1024)

    @model_validator(mode="after")
    def _mode_rules(self) -> "StreamStartRequest":
        """engine_id present => model_id required; absent => inference-only
        fields forbidden (contract allOf)."""
        if self.engine_id is not None:
            if not self.model_id:
                raise ValueError("model_id is required when engine_id is set")
        else:
            forbidden = [
                name for name, supplied in (
                    ("model_id", self.model_id is not None),
                    ("device_id", self.device_id is not None),
                    ("engine_options", self.engine_options is not None),
                    ("annotate", self.annotate),
                ) if supplied
            ]
            if forbidden:
                raise ValueError(
                    f"{', '.join(forbidden)} require engine_id (video-only mode)")
        return self

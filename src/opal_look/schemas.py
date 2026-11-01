"""Shared contract-derived pydantic models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .errors import ApiError

IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"

Task = Literal["detection", "classification", "segmentation", "pose", "ocr"]
TASKS = ("detection", "classification", "segmentation", "pose", "ocr")

SOURCE_TYPES = ("camera", "rtsp", "http", "host_video", "media")

Identifier = str


def reject_null_fields(supplied: dict[str, Any]) -> None:
    """Explicit null is not a valid value for non-nullable patch fields."""
    if any(value is None for value in supplied.values()):
        raise ApiError(422, "Explicit null values are not allowed in updates.")


class EngineUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    enabled: bool | None = Field(default=None)
    config: dict[str, Any] | None = Field(default=None)


class ModelCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    model_id: str = Field(pattern=IDENTIFIER_PATTERN)
    name: str = Field(min_length=1)
    engine_id: str = Field(pattern=IDENTIFIER_PATTERN)
    resource: dict[str, Any]
    enabled: bool = Field(default=True)


class ModelUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    engine_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    resource: dict[str, Any] | None = Field(default=None)
    enabled: bool | None = Field(default=None)

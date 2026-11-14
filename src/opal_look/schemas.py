"""Pydantic DTOs shared across routers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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

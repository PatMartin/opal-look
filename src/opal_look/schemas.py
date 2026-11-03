"""Shared contract-derived pydantic models."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class EnginePatch(BaseModel):
    """v1.5 EnginePatch: enabled and/or engine options (validated by adapter)."""
    model_config = ConfigDict(strict=True, extra="forbid")

    enabled: bool | None = Field(default=None)
    options: dict[str, Any] | None = Field(default=None)


class ModelCreate(BaseModel):
    """v1.5 ModelCreate: registers an already-provisioned resource."""
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    engine_id: str = Field(pattern=IDENTIFIER_PATTERN)
    resource_ref: str = Field(min_length=1)
    tasks: list[str] = Field(min_length=1)
    options: dict[str, Any] | None = Field(default=None)


class ModelPatch(BaseModel):
    """v1.5 ModelPatch: metadata/options only."""
    model_config = ConfigDict(strict=True, extra="forbid")

    display_name: str | None = Field(default=None, min_length=1)
    options: dict[str, Any] | None = Field(default=None)


# -- sources ----------------------------------------------------------------

SourceType = Literal["camera", "rtsp", "http", "host_video", "media"]


class SourceCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    source_id: str = Field(pattern=IDENTIFIER_PATTERN)
    name: str = Field(min_length=1)
    type: SourceType
    locator: str = Field(min_length=1)
    credential_ref: str | None = Field(default=None)
    enabled: bool = Field(default=True)
    source_options: dict[str, Any] = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    type: SourceType | None = Field(default=None)
    locator: str | None = Field(default=None, min_length=1)
    credential_ref: str | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    source_options: dict[str, Any] | None = Field(default=None)


# -- profiles ---------------------------------------------------------------

class Point(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class Region(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    region_id: str = Field(pattern=IDENTIFIER_PATTERN)
    polygon: list[Point] = Field(min_length=3)


class AnalysisSettings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    confidence: float = Field(default=0.25, ge=0, le=1)
    class_labels: list[str] = Field(default_factory=list)
    image_size: int | None = Field(default=None, ge=32)
    regions: list[Region] = Field(default_factory=list)
    max_fps: float = Field(default=5, gt=0)
    file_mode: Literal["sampled", "every_frame"] = Field(default="sampled")
    tracking: bool = Field(default=False)
    segmentation_kind: Literal["instance", "semantic"] = Field(default="instance")
    engine_options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("class_labels")
    @classmethod
    def _unique_labels(cls, labels: list[str]) -> list[str]:
        if len(set(labels)) != len(labels):
            raise ValueError("class_labels entries must be unique")
        return labels


class ProfileCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(min_length=1)
    model_id: str = Field(pattern=IDENTIFIER_PATTERN)
    task: Task
    settings: AnalysisSettings | None = Field(default=None)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    model_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    task: Task | None = Field(default=None)
    settings: AnalysisSettings | None = Field(default=None)


# -- analyze ----------------------------------------------------------------

class MediaFrameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["media"]
    media_id: str = Field(pattern=IDENTIFIER_PATTERN)


class SourceFrameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["source"]
    source_id: str = Field(pattern=IDENTIFIER_PATTERN)
    position_ms: int | None = Field(default=None, ge=0)


FrameInput = Annotated[
    MediaFrameInput | SourceFrameInput, Field(discriminator="kind")
]


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    profile_id: int | None = Field(default=None, ge=1)
    model_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    task: Task | None = Field(default=None)
    settings: AnalysisSettings | None = Field(default=None)
    input: FrameInput
    store_result: bool = Field(default=True)

    @model_validator(mode="after")
    def _no_explicit_nulls(self) -> "AnalyzeRequest":
        for name in self.model_fields_set:
            if getattr(self, name) is None and name != "input":
                raise ValueError(f"explicit null is not allowed for {name}")
        return self


class ReconnectPolicy(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    enabled: bool = Field(default=True)
    max_attempts: int = Field(default=10, ge=0)
    initial_delay_ms: int = Field(default=1000, ge=100)
    max_delay_ms: int = Field(default=30000, ge=100)

    @model_validator(mode="after")
    def _bounds(self) -> "ReconnectPolicy":
        if self.max_delay_ms < self.initial_delay_ms:
            raise ValueError("max_delay_ms must be >= initial_delay_ms")
        return self


class SessionCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    profile_id: int | None = Field(default=None, ge=1)
    model_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    task: Task | None = Field(default=None)
    settings: AnalysisSettings | None = Field(default=None)
    source_id: str = Field(pattern=IDENTIFIER_PATTERN)
    store_results: bool = Field(default=True)
    start_position_ms: int = Field(default=0, ge=0)
    end_position_ms: int | None = Field(default=None, ge=0)
    reconnect: ReconnectPolicy | None = Field(default=None)

    @model_validator(mode="after")
    def _check(self) -> "SessionCreate":
        for name in ("profile_id", "model_id", "task", "settings", "end_position_ms", "reconnect"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"explicit null is not allowed for {name}")
        if self.end_position_ms is not None and self.end_position_ms <= self.start_position_ms:
            raise ValueError("end_position_ms must exceed start_position_ms")
        return self

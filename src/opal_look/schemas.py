"""Shared contract-derived pydantic models."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import ApiError

IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"

Task = Literal["detection", "classification", "segmentation", "pose", "ocr"]
TASKS = ("detection", "classification", "segmentation", "pose", "ocr")

SOURCE_TYPES = ("rtsp", "http", "camera", "file", "media", "image")

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

SourceType = Literal["usb", "rtsp", "http_mjpeg", "file", "media", "adapter"]


class SourceZone(BaseModel):
    """v1.5 SourceZone: source-local named region (polygon >=3, line ==2)."""
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    name: str = Field(min_length=1)
    kind: Literal["polygon", "line"]
    points: list["Point"] = Field(min_length=2)
    enabled: bool = Field(default=True)

    @model_validator(mode="after")
    def _check_geometry(self) -> "SourceZone":
        if self.kind == "polygon" and len(self.points) < 3:
            raise ValueError("polygon zones require at least 3 points")
        if self.kind == "line" and len(self.points) != 2:
            raise ValueError("line zones require exactly 2 points")
        return self


def _unique_zone_ids(zones: list[SourceZone] | None) -> list[SourceZone] | None:
    if zones:
        ids = [z.id for z in zones]
        if len(ids) != len(set(ids)):
            raise ValueError("zone ids must be unique within a source")
    return zones


class SourceCreate(BaseModel):
    """v1.5 SourceCreate."""
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    kind: SourceType
    name: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    secret_ref: str | None = Field(default=None)
    options: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = Field(default=True)

    @model_validator(mode="after")
    def _check(self) -> "SourceCreate":
        if self.secret_ref is not None and not self.secret_ref.strip():
            raise ValueError("secret_ref must be non-empty when provided")
        return self


class SourcePatch(BaseModel):
    """Upstream SourcePatch: zones are a standalone resource now."""
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    locator: str | None = Field(default=None, min_length=1)
    secret_ref: str | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    options: dict[str, Any] | None = Field(default=None)

    @model_validator(mode="after")
    def _check(self) -> "SourcePatch":
        if "secret_ref" in self.model_fields_set and self.secret_ref is not None \
                and not self.secret_ref.strip():
            raise ValueError("secret_ref must be non-empty when provided")
        return self


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


# -- pipelines (v1.5) ----------------------------------------------------------

class RetentionOptions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    persist_observations: bool = Field(default=False)
    save_raw_frames: bool = Field(default=False)
    save_annotated_frames: bool = Field(default=False)
    ttl_seconds: int | None = Field(default=None, ge=0)


class FilterSpec(BaseModel):
    """v1.5 FilterSpec; per-type parameter bounds validated semantically."""
    model_config = ConfigDict(strict=True, extra="forbid")

    type: Literal["grayscale", "brightness_contrast", "blur", "sharpen",
                  "threshold", "edges", "rotate", "flip", "crop", "resize", "motion"]
    parameters: dict[str, Any] = Field(default_factory=dict)


class MotionGateOptions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    motion_stage_id: str = Field(pattern=IDENTIFIER_PATTERN)
    sample_every_n_frames: int = Field(default=30, ge=1)
    on_unknown: Literal["run_inference", "skip"] = Field(default="run_inference")


class AnnotationOptions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    enabled: bool = Field(default=True)
    show_boxes: bool = Field(default=True)
    show_labels: bool = Field(default=True)
    show_confidence: bool = Field(default=True)
    show_track_ids: bool = Field(default=False)
    show_zones: bool = Field(default=False)
    classes: list[str] | None = Field(default=None)
    min_confidence: float | None = Field(default=None, ge=0, le=1)


class VideoProcessingOptions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    target_fps: float | None = Field(default=None, ge=0.1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    quality: int | None = Field(default=None, ge=1, le=100)


class InferenceOptions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    target_fps: float | None = Field(default=None, ge=0.1)
    max_frames: int | None = Field(default=None, ge=1)
    confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    classes: list[str] | None = Field(default=None)
    roi: list[Point] | None = Field(default=None, min_length=3)
    engine_options: dict[str, Any] | None = Field(default=None)
    video: VideoProcessingOptions | None = Field(default=None)
    annotations: AnnotationOptions | None = Field(default=None)



class ProcessingStageOptions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    filter: FilterSpec | None = Field(default=None)
    gate: MotionGateOptions | None = Field(default=None)
    annotation: AnnotationOptions | None = Field(default=None)
    video: VideoProcessingOptions | None = Field(default=None)


class PipelineStage(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    kind: Literal["preprocess", "inference", "tracker", "filter", "transform", "annotate"]
    model_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    task: str | None = Field(default=None)
    inputs: list[str] | None = Field(default=None)
    options: dict[str, Any] | None = Field(default=None)
    enabled: bool = Field(default=True)
    portable: ProcessingStageOptions | None = Field(default=None)
    phase: Literal["inference_input", "presentation"] | None = Field(default=None)


def _pipeline_mode_error() -> ValueError:
    return ValueError(
        "exactly one mode required: simple (model_id + task, no stages) "
        "or advanced (stages, no model_id/task)"
    )


class PipelineCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    name: str = Field(min_length=1)
    description: str | None = Field(default=None)
    model_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    task: str | None = Field(default=None)
    stages: list[PipelineStage] | None = Field(default=None, min_length=1)
    options: InferenceOptions | None = Field(default=None)
    retention: RetentionOptions | None = Field(default=None)

    @model_validator(mode="after")
    def _one_mode(self) -> "PipelineCreate":
        simple = self.model_id is not None and self.task is not None
        if (self.model_id is None) != (self.task is None):
            raise _pipeline_mode_error()
        if simple == (self.stages is not None):
            raise _pipeline_mode_error()
        return self


class PipelinePatch(BaseModel):
    """Merge-patch; explicit null clears model_id/task/stages for mode switch."""
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None)
    model_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    task: str | None = Field(default=None)
    stages: list[PipelineStage] | None = Field(default=None, min_length=1)
    options: InferenceOptions | None = Field(default=None)
    retention: RetentionOptions | None = Field(default=None)


# -- v1.5 analyze submission ---------------------------------------------------

class AnalyzeSourceInput(BaseModel):
    """v1.5 SourceInput: exactly one of source_id | media_id."""
    model_config = ConfigDict(strict=True, extra="forbid")

    source_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    media_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    frame_at_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one_input(self) -> "AnalyzeSourceInput":
        if (self.source_id is None) == (self.media_id is None):
            raise ValueError("exactly one of source_id or media_id is required")
        return self


class AnalyzeSubmission(BaseModel):
    """v1.5 POST /api/v1/analyze/ body."""
    model_config = ConfigDict(strict=True, extra="forbid")

    source: AnalyzeSourceInput
    pipeline_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    options: InferenceOptions | None = Field(default=None)
    retention: RetentionOptions | None = Field(default=None)

    @model_validator(mode="after")
    def _no_explicit_nulls(self) -> "AnalyzeSubmission":
        for name in self.model_fields_set:
            if getattr(self, name) is None and name != "source":
                raise ValueError(f"explicit null is not allowed for {name}")
        return self


class ImageAnalyzeOptions(BaseModel):
    """v1.5 JSON 'request' part for POST /api/v1/analyze/image."""
    model_config = ConfigDict(strict=True, extra="forbid")

    pipeline_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    options: InferenceOptions | None = Field(default=None)
    retention: RetentionOptions | None = Field(default=None)

    @model_validator(mode="after")
    def _no_explicit_nulls(self) -> "ImageAnalyzeOptions":
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"explicit null is not allowed for {name}")
        return self


class CaptureRequest(BaseModel):
    """v1.5 POST /sources/{id}/capture: always retains one exact frame."""
    model_config = ConfigDict(strict=True, extra="forbid")

    pipeline_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    annotated: bool = Field(default=False)
    ttl_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _no_explicit_nulls(self) -> "CaptureRequest":
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"explicit null is not allowed for {name}")
        return self


# -- monitors (v1.5) -----------------------------------------------------------

class MonitorCondition(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    event: Literal[
        "object_appears", "object_disappears", "enters_zone", "exits_zone",
        "line_crosses", "count_threshold", "dwell_time", "motion_detected",
    ]
    zone_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    classes: list[str] | None = Field(default=None, min_length=1)
    threshold: float | None = Field(default=None, ge=0)
    minimum_duration_ms: int | None = Field(default=None, ge=0)
    cooldown_ms: int | None = Field(default=None, ge=0)
    enabled: bool = Field(default=True)
    capture_on_match: bool = Field(default=False)
    clip_on_match: bool = Field(default=False)


class MonitorCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(pattern=IDENTIFIER_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    source_id: str = Field(pattern=IDENTIFIER_PATTERN)
    pipeline_id: str = Field(pattern=IDENTIFIER_PATTERN)
    enabled: bool = Field(default=True)
    restart_policy: Literal["on_failure", "always", "never"] = "on_failure"
    options: InferenceOptions | None = Field(default=None)
    retention: RetentionOptions | None = Field(default=None)
    conditions: list[MonitorCondition] = Field(default_factory=list)
    publish_events: bool = Field(default=False)

    @model_validator(mode="after")
    def _zone_conditions_have_zone(self) -> "MonitorCreate":
        for c in self.conditions:
            if c.event in ("enters_zone", "exits_zone", "line_crosses")                     and not c.zone_id:
                raise ValueError(f"condition {c.id!r}: zone_id is required")
        return self


class MonitorPatch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    source_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    pipeline_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    enabled: bool | None = Field(default=None)
    restart_policy: Literal["on_failure", "always", "never"] | None = None
    options: InferenceOptions | None = Field(default=None)
    retention: RetentionOptions | None = Field(default=None)
    conditions: list[MonitorCondition] | None = Field(default=None)
    publish_events: bool | None = Field(default=None)

    @model_validator(mode="after")
    def _zone_conditions_have_zone(self) -> "MonitorPatch":
        if self.conditions is not None:
            for c in self.conditions:
                if c.event in ("enters_zone", "exits_zone", "line_crosses")                         and not c.zone_id:
                    raise ValueError(f"condition {c.id!r}: zone_id is required")
        return self


# -- jobs (v1.5) ---------------------------------------------------------------

class MediaRange(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _end_after_start(self) -> "MediaRange":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ExportOptions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    format: Literal["mp4", "webm", "jpeg", "png"] = "jpeg"
    annotated: bool = Field(default=False)
    include_audio: bool = Field(default=False)
    quality: int | None = Field(default=None, ge=1, le=100)


class JobCreate(BaseModel):
    """v1.5 JobCreate: exactly one of source_id/media_id."""
    model_config = ConfigDict(strict=True, extra="forbid")

    kind: Literal["video_analysis", "media_export"]
    source_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    media_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    pipeline_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    range: MediaRange | None = Field(default=None)
    options: InferenceOptions | None = Field(default=None)
    retention: RetentionOptions | None = Field(default=None)
    output: ExportOptions | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_shape(self) -> "JobCreate":
        if (self.source_id is None) == (self.media_id is None):
            raise ValueError("exactly one of source_id or media_id is required")
        if self.kind == "media_export" and self.output is None:
            raise ValueError("media_export requires output options")
        return self


# -- recordings (v1.5) ----------------------------------------------------------

class RecordingCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    source_id: str = Field(pattern=IDENTIFIER_PATTERN)
    pipeline_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    include_audio: bool = Field(default=False)
    max_duration_seconds: int | None = Field(default=None, ge=1)
    output: ExportOptions | None = Field(default=None)


# -- configuration import -----------------------------------------------------
# Body is the bare OpalConfigExport bundle (kernel shape); optional
# source_bindings section rebinding is handled in routers/configuration.py.

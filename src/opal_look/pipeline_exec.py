"""Minimal executor for validated pipeline DAGs (v1.5, step 09).

Runs ordered stages over ONE decoded frame (the caller decodes once):
preprocess/transform/filter (portable.filter) feed the inference-input
image; motion filter stages produce temporal verdicts (unknown / warmup /
discontinuity / moving / static) against a per-key baseline; inference
stages call the registered adapter (honoring portable.gate skip/unknown
semantics with periodic forced sampling); tracker stages attach track ids
only when the engine advertises tracking; annotate/presentation-phase
stages are isolated to the presentation image and never feed inference.

Contract anchors: PipelineStage semantics, Observation/ObservationItem
shapes, x-opal-filter-catalog ("Motion requires sequential source frames,
resets on source discontinuity, and warmup produces unknown state").

Result: {"observations": [Observation...], "trace": [stage_id...],
         "warnings": [...], "presentation": {"image": PIL.Image|None}}
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

from .engines import ENGINE_REGISTRY, EngineUnavailable, model_runtime
from .errors import ApiError
from .schemas import PipelineStage
from .store import Store
from .timeutil import now_iso

_MOTION_STATES_MAX = 64  # bounded per-process motion baselines


# -- image filters (inference-input) -------------------------------------------

def _apply_filter(image, spec) -> Any:
    """Apply one portable filter spec to a PIL image and return it."""
    from PIL import ImageEnhance, ImageFilter, ImageOps

    p = spec.parameters or {}
    t = spec.type
    if t == "grayscale":
        return ImageOps.grayscale(image).convert("RGB")
    if t == "brightness_contrast":
        out = image
        if "brightness" in p:
            out = ImageEnhance.Brightness(out).enhance(1 + p["brightness"])
        if "contrast" in p:
            out = ImageEnhance.Contrast(out).enhance(p["contrast"])
        return out
    if t == "blur":
        return image.filter(ImageFilter.BoxBlur(max(1, p.get("kernel_size", 3) // 2)))
    if t == "sharpen":
        return ImageEnhance.Sharpness(image).enhance(1 + p.get("amount", 0))
    if t == "threshold":
        thr = p.get("threshold", 128)
        return ImageOps.grayscale(image).point(lambda v: 255 if v >= thr else 0).convert("RGB")
    if t == "edges":
        lo = int(p.get("low_threshold", 0))
        hi = int(p.get("high_threshold", 255))
        return ImageOps.grayscale(image).filter(ImageFilter.FIND_EDGES).point(
            lambda v: min(255, max(lo, min(v, hi)))).convert("RGB")
    if t == "rotate":
        return image.rotate(-(p.get("degrees", 0) or 0), expand=True)
    if t == "flip":
        return ImageOps.flip(image) if p.get("axis") == "vertical" else ImageOps.mirror(image)
    if t == "crop":
        r = p["roi"]
        w, h = image.width, image.height
        return image.crop((round(r["x"] * w), round(r["y"] * h),
                           round((r["x"] + r["width"]) * w), round((r["y"] + r["height"]) * h)))
    if t == "resize":
        w = p.get("width") or image.width
        h = p.get("height") or image.height
        return image.resize((w, h))
    if t == "motion":
        return image  # handled by _motion_verdict
    raise ApiError(422, f"Unsupported filter type: {t!r}", code="unsupported_filter")


# -- motion --------------------------------------------------------------------

def _motion_score(a, b) -> float:
    """Mean absolute channel difference ratio in [0,1] on downsampled frames."""
    from PIL import ImageChops, ImageOps

    g1 = ImageOps.grayscale(a.convert("RGB").resize((16, 16)))
    g2 = ImageOps.grayscale(b.convert("RGB").resize((16, 16)))
    diff = ImageChops.difference(g1, g2)
    return sum(diff.tobytes()) / (255.0 * 256)


def _motion_verdict(stage: PipelineStage, image, state: dict | None,
                    warnings: list[str]) -> str:
    """Temporal verdict: unknown|warmup|discontinuity|moving|static."""
    params = (stage.portable.filter.parameters or {}) if stage.portable else {}
    warmup = int(params.get("warmup_frames", 3))
    if state is None:
        warnings.append(f"motion stage {stage.id!r}: no sequential frames; verdict unknown")
        return "unknown"
    prev = state.get("prev")
    state["frames"] = state.get("frames", 0) + 1
    if prev is not None and prev.size != image.size:
        state["prev"] = image.copy()
        warnings.append(f"motion stage {stage.id!r}: discontinuity; baseline reset")
        return "discontinuity"
    if prev is None:
        state["prev"] = image.copy()
        return "warmup"
    score = _motion_score(prev, image)
    state["prev"] = image.copy()
    if state["frames"] <= warmup:
        return "warmup"
    sensitivity = params.get("sensitivity", 0.5)
    threshold = max(0.02, 0.5 * (1.0 - sensitivity))
    return "moving" if score >= threshold else "static"


def _motion_state_bucket(motion_states: dict | None, key: str) -> dict | None:
    if motion_states is None:
        return None
    if key not in motion_states and len(motion_states) >= _MOTION_STATES_MAX:
        motion_states.pop(next(iter(motion_states)))  # evict oldest (bounded)
    return motion_states.setdefault(key, {"prev": None, "frames": 0, "inference_since": 0})


# -- observation emission -------------------------------------------------------

def _items_from_payload(task: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if task == "detection":
        for o in payload.get("objects", []):
            items.append({
                "type": "detection", "label": o.get("label"),
                "score": o.get("confidence"), "box": o.get("box"),
                "track_id": o.get("track_id"),
            })
    elif task == "classification":
        for c in payload.get("classes", []):
            items.append({"type": "classification", "label": c.get("label"),
                          "score": c.get("confidence")})
    elif task == "segmentation":
        for inst in payload.get("instances", []):
            items.append({
                "type": "segmentation", "label": inst.get("label"),
                "score": inst.get("confidence"), "box": inst.get("box"),
                "payload": {"mask": inst.get("mask")},
            })
        if payload.get("kind") == "semantic":
            for c in (payload.get("map") or {}).get("classes", []):
                items.append({"type": "segmentation", "label": c.get("label"),
                              "score": c.get("confidence"),
                              "payload": {"semantic": True}})
    elif task == "pose":
        for pose in payload.get("poses", []):
            items.append({"type": "pose", "label": pose.get("label"),
                          "score": pose.get("confidence"),
                          "payload": {"keypoints": pose.get("keypoints")}})
    elif task == "ocr":
        for t in payload.get("texts", []):
            items.append({"type": "ocr", "text": t.get("text"),
                          "score": t.get("confidence"), "box": t.get("box")})
    return items


def _observation(store, *, pipeline_id, revision, stage_id, engine_id,
                 model_id, task, image, items, warnings, source_id,
                 media_id, frame_index, transaction_id, request_id) -> dict[str, Any]:
    obs = {
        "id": f"obs-{engine_id or 'x'}-{request_id[:8]}-{stage_id}-{len(items)}",
        "created_at": now_iso(),
        "observed_at": now_iso(),
        "source_id": source_id,
        "media_id": media_id,
        "monitor_id": None,
        "job_id": None,
        "pipeline_id": pipeline_id,
        "pipeline_revision": str(revision),
        "stage_id": stage_id,
        "engine_id": engine_id,
        "model_id": model_id,
        "task": task,
        "frame_index": frame_index,
        "media_time_ms": None,
        "image": {"width": image.width, "height": image.height, "timestamp": None},
        "items": items,
        "warnings": warnings,
        "session_context_id": None,
        "transaction_id": transaction_id,
        "request_id": request_id,
    }
    return obs


# -- executor -------------------------------------------------------------------

def _stage_list(store: Store, row) -> list[PipelineStage]:
    from .schemas import PipelineStage as _PS

    stages = json.loads(row["stages"])
    if stages:
        return [_PS(**s) for s in stages]
    # simple mode: synthesized single inference stage
    return [_PS(id="inference", kind="inference",
                model_id=row["model_id"], task=row["task"])]


def run_pipeline(store: Store, pipeline_row, image, *, source_id=None,
                 media_id=None, frame_index=None, transaction_id: str,
                 request_id: str, motion_states: dict | None = None,
                 options=None) -> dict[str, Any]:
    pipeline_id = pipeline_row["pipeline_id"]
    stages = _stage_list(store, pipeline_row)
    trace: list[str] = []
    warnings: list[str] = []
    observations: list[dict[str, Any]] = []
    outputs: dict[str, dict] = {}   # stage_id -> {image, motion, observation}
    presentation_image = None

    motion_key = source_id or media_id or "still"
    motion_state = _motion_state_bucket(motion_states, f"{pipeline_id}:{motion_key}")

    started = time.monotonic()

    def feed_image(stage: PipelineStage):
        if not stage.inputs:
            return image
        last = outputs.get(stage.inputs[-1])
        if last is not None and last.get("image") is not None:
            return last["image"]
        return image

    for st in stages:
        trace.append(st.id)
        if not st.enabled:
            continue

        if st.kind in ("preprocess", "transform", "filter"):
            if st.phase == "presentation":
                if presentation_image is None:
                    presentation_image = image.copy()
                if st.portable and st.portable.filter:
                    presentation_image = _apply_filter(presentation_image,
                                                       st.portable.filter)
                outputs[st.id] = {"image": None, "presentation": True}
                continue
            spec = st.portable.filter if st.portable else None
            if st.kind == "filter" and spec and spec.type == "motion":
                verdict = _motion_verdict(st, feed_image(st), motion_state, warnings)
                outputs[st.id] = {"image": feed_image(st), "motion": verdict}
                if verdict == "moving":
                    observations.append(_observation(
                        store, pipeline_id=pipeline_id,
                        revision=pipeline_row["revision"], stage_id=st.id,
                        engine_id=None, model_id=None, task="motion",
                        image=feed_image(st),
                        items=[{"type": "motion",
                                "payload": {"state": verdict}}],
                        warnings=[], source_id=source_id, media_id=media_id,
                        frame_index=frame_index, transaction_id=transaction_id,
                        request_id=request_id))
                continue
            inp = feed_image(st)
            out = _apply_filter(inp, spec) if spec else inp
            outputs[st.id] = {"image": out}
            continue

        if st.kind == "inference":
            model_row = store.models.get(st.model_id)
            if model_row is None:
                raise ApiError(422, f"Pipeline stage {st.id!r}: model {st.model_id!r} is not registered.")
            runtime = model_runtime(store, model_row)
            if not runtime["enabled"] or not runtime["available"]:
                raise ApiError(503, f"Pipeline stage {st.id!r}: model {st.model_id!r} is unavailable.")
            if st.task not in runtime["tasks"]:
                raise ApiError(422, f"Pipeline stage {st.id!r}: task {st.task!r} unsupported by model.")
            adapter = ENGINE_REGISTRY.get(runtime["engine_id"])
            if adapter is None:
                raise ApiError(503, f"Pipeline stage {st.id!r}: engine {runtime['engine_id']!r} is not installed.")

            skip_reason = None
            if st.portable and st.portable.gate:
                gate = st.portable.gate
                ref = outputs.get(gate.motion_stage_id)
                verdict = ref.get("motion") if ref else "unknown"
                if motion_state is not None:
                    motion_state["inference_since"] = motion_state.get("inference_since", 0) + 1
                if verdict == "static":
                    # periodic sampling prevents indefinite skipped inference
                    every = gate.sample_every_n_frames
                    seen = (motion_state or {}).get("inference_since", 0)
                    if seen % max(1, every) != 0:
                        skip_reason = "no motion (gated)"
                elif verdict in ("unknown", "warmup"):
                    if gate.on_unknown == "skip":
                        skip_reason = f"motion {verdict} (gated on unknown)"

            if skip_reason:
                observations.append(_observation(
                    store, pipeline_id=pipeline_id,
                    revision=pipeline_row["revision"], stage_id=st.id,
                    engine_id=runtime["engine_id"], model_id=st.model_id,
                    task=st.task, image=feed_image(st), items=[],
                    warnings=[f"inference skipped: {skip_reason}"],
                    source_id=source_id, media_id=media_id,
                    frame_index=frame_index, transaction_id=transaction_id,
                    request_id=request_id))
                warnings.append(f"stage {st.id!r}: inference skipped ({skip_reason})")
                outputs[st.id] = {"image": feed_image(st), "skipped": True}
                continue

            inp = feed_image(st)
            engine_options = dict((st.options or {}).get("engine_options") or {})
            try:
                payload = adapter.infer(inp.width, inp.height, st.task,
                                        runtime, engine_options, frame_index or 0)
            except EngineUnavailable as exc:
                raise ApiError(503, f"Pipeline stage {st.id!r}: engine unavailable: {exc}")
            items = _items_from_payload(st.task, payload)
            observations.append(_observation(
                store, pipeline_id=pipeline_id, revision=pipeline_row["revision"],
                stage_id=st.id, engine_id=runtime["engine_id"],
                model_id=st.model_id, task=st.task, image=inp, items=items,
                warnings=[], source_id=source_id, media_id=media_id,
                frame_index=frame_index, transaction_id=transaction_id,
                request_id=request_id))
            outputs[st.id] = {"image": inp, "observation": observations[-1],
                              "payload": payload}
            continue

        if st.kind == "tracker":
            # Requires advertised tracking on the upstream inference engine.
            upstream = None
            for ref in st.inputs or []:
                out = outputs.get(ref)
                if out and out.get("observation") is not None:
                    upstream = out["observation"]
            if upstream is None:
                raise ApiError(422, f"Pipeline stage {st.id!r}: tracker needs an inference input.")
            mrow = store.models.get(upstream["model_id"])
            rt = model_runtime(store, mrow) if mrow is not None else {}
            if not rt.get("tracking"):
                raise ApiError(422, f"Pipeline stage {st.id!r}: engine does not advertise tracking.")
            for i, item in enumerate(upstream["items"]):
                if item.get("track_id") is None:
                    item["track_id"] = f"{st.id}-{i}"
                    item["track_epoch"] = "0"
            outputs[st.id] = {"image": feed_image(st)}
            continue

        if st.kind == "annotate":
            if presentation_image is None:
                presentation_image = image.copy()
            opts = st.portable.annotation if st.portable else None
            if opts is None or opts.enabled:
                _annotate(presentation_image, observations, opts, warnings)
            outputs[st.id] = {"image": None, "presentation": True}
            continue

    elapsed_ms = round((time.monotonic() - started) * 1000, 3)
    return {
        "observations": observations,
        "trace": trace,
        "warnings": warnings,
        "processing_ms": elapsed_ms,
        "presentation": {"image": presentation_image},
    }


def _annotate(image, observations, opts, warnings: list[str]) -> None:
    """Draw boxes/labels on the presentation image (presentation-only)."""
    try:
        from PIL import ImageDraw
    except ImportError:
        warnings.append("annotation unavailable: PIL ImageDraw missing")
        return
    draw = ImageDraw.Draw(image)
    show_boxes = opts.show_boxes if opts else True
    show_labels = opts.show_labels if opts else True
    show_conf = opts.show_confidence if opts else True
    show_tracks = getattr(opts, "show_track_ids", False) if opts else False
    allowed = set(opts.classes) if opts and opts.classes else None
    min_conf = opts.min_confidence if opts else None
    w, h = image.width, image.height
    for obs in observations:
        for item in obs.get("items", []):
            if allowed is not None and item.get("label") not in allowed:
                continue
            if min_conf is not None and item.get("score") is not None \
                    and item["score"] < min_conf:
                continue
            box = item.get("box")
            if box and show_boxes:
                xy = (box["x"] * w, box["y"] * h,
                      (box["x"] + box["width"]) * w, (box["y"] + box["height"]) * h)
                draw.rectangle(xy, outline=(255, 64, 64), width=2)
                if show_labels and item.get("label"):
                    text = str(item["label"])
                    if show_conf and item.get("score") is not None:
                        text += f" {item['score']:.2f}"
                    if show_tracks and item.get("track_id"):
                        text += f" #{item['track_id']}"
                    draw.text((xy[0], xy[1]), text, fill=(255, 64, 64))

"""DAG + semantic validation for advanced pipelines (v1.5, step 08).

Validates ordered stage topology and portable-stage parameters WITHOUT
running anything. Every problem becomes a ValidationIssue-shaped dict
{path, code, message, severity}; callers turn non-empty results into the
contract validation response or a 422 details payload.

Rules enforced (normative sources: PipelineStage, x-opal-filter-catalog):
- stage ids unique; inputs may reference EARLIER stage ids only
  (forward refs and self/cyclic refs are invalid);
- inference stages require model_id + task, a registered model, a
  model-supported task, and valid engine_options;
- tracker stages require at least one inference input;
- filter stages must carry portable.filter with a known type and
  strictly-validated per-type parameters (unknown keys fail);
- portable.gate allowed only on inference stages; its motion_stage_id
  must reference an earlier stage whose portable.filter.type == "motion";
- portable.annotation only on annotate stages; portable.video only on
  preprocess/transform; portable.filter only on filter stages;
- presentation-phase stages must not feed inference stages.
"""

from __future__ import annotations

from typing import Any

from .engines import ENGINE_REGISTRY, model_runtime
from .schemas import PipelineStage
from .store import Store


def _issue(path: str, code: str, message: str, severity: str = "error") -> dict:
    return {"path": path, "code": code, "message": message, "severity": severity}


# Per-type parameter rules from x-opal-filter-catalog:
# {key: (required, kind, check)} — kind 'num'|'int'|'enum'|'roi'|'rect'
def _num(lo, hi):
    def f(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi
    return f


def _int(lo, hi=None):
    def f(v):
        ok = isinstance(v, int) and not isinstance(v, bool) and v >= lo
        return ok and (hi is None or v <= hi)
    return f


def _odd_int(lo, hi):
    def f(v):
        return _int(lo, hi)(v) and v % 2 == 1
    return f


def _enum(*vals):
    return lambda v: v in vals


def _roi(v):
    return isinstance(v, list) and len(v) >= 3 and all(
        isinstance(p, dict) and isinstance(p.get("x"), (int, float))
        and isinstance(p.get("y"), (int, float)) and 0 <= p["x"] <= 1 and 0 <= p["y"] <= 1
        for p in v)


def _rect(v):
    return isinstance(v, dict) and all(
        isinstance(v.get(k), (int, float)) and 0 <= v[k] <= 1
        for k in ("x", "y", "width", "height"))


FILTER_PARAMETERS: dict[str, dict[str, tuple[bool, Any]]] = {
    "grayscale": {},
    "brightness_contrast": {
        "brightness": (False, _num(-1, 1)),
        "contrast": (False, _num(0, 4)),
    },
    "blur": {"kernel_size": (False, _odd_int(3, 31))},
    "sharpen": {"amount": (False, _num(0, 3))},
    "threshold": {"threshold": (False, _num(0, 255))},
    "edges": {
        "low_threshold": (False, _num(0, 255)),
        "high_threshold": (False, _num(0, 255)),
    },
    "rotate": {"degrees": (False, _enum(0, 90, 180, 270))},
    "flip": {"axis": (False, _enum("horizontal", "vertical"))},
    "crop": {"roi": (True, _rect)},
    "resize": {
        "width": (False, _int(1)),
        "height": (False, _int(1)),
    },
    "motion": {
        "sensitivity": (False, _num(0, 1)),
        "minimum_area": (False, _int(1)),
        "warmup_frames": (False, _int(1)),
        "visualization": (False, _enum("none", "highlight", "mask")),
        "roi": (False, _roi),
    },
}


def _check_filter_params(path: str, spec) -> list[dict]:
    issues: list[dict] = []
    rules = FILTER_PARAMETERS[spec.type]
    params = spec.parameters or {}
    for key in sorted(set(params) - set(rules)):
        issues.append(_issue(f"{path}.parameters",
                             "unknown_filter_parameter",
                             f"filter {spec.type!r} has no parameter {key!r}"))
    for key, (required, check) in rules.items():
        if key not in params:
            if required:
                issues.append(_issue(f"{path}.parameters",
                                     "missing_filter_parameter",
                                     f"filter {spec.type!r} requires parameter {key!r}"))
            continue
        if not check(params[key]):
            issues.append(_issue(f"{path}.parameters",
                                 "invalid_filter_parameter",
                                 f"filter {spec.type!r} parameter {key!r} is out of range or malformed"))
    if spec.type == "resize" and "width" not in params and "height" not in params:
        issues.append(_issue(f"{path}.parameters",
                             "missing_filter_parameter",
                             "resize requires width and/or height"))
    if spec.type == "edges":
        lo, hi = params.get("low_threshold"), params.get("high_threshold")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
            issues.append(_issue(f"{path}.parameters",
                                 "invalid_filter_parameter",
                                 "edges requires low_threshold <= high_threshold"))
    return issues


_PORTABLE_KINDS = {
    "filter": {"filter"},
    "annotate": {"annotation"},
    "inference": {"gate"},
    "preprocess": {"video", "filter"},
    "transform": {"video", "filter"},
    "tracker": set(),
}


def validate_stages(store: Store, stages: list[PipelineStage]) -> list[dict]:
    issues: list[dict] = []
    seen: dict[str, PipelineStage] = {}

    ids = [s.id for s in stages]
    if len(ids) != len(set(ids)):
        issues.append(_issue("stages", "duplicate_stage_id",
                             "stage ids must be unique"))

    for idx, st in enumerate(stages):
        path = f"stages[{idx}]"
        # inputs must reference earlier stage ids only
        for ref in st.inputs or []:
            if ref not in seen:
                issues.append(_issue(
                    f"{path}.inputs", "invalid_stage_input",
                    f"input {ref!r} does not reference an earlier stage"))

        # kind-specific requirements
        if st.kind == "inference":
            if st.model_id is None or st.task is None:
                issues.append(_issue(
                    path, "incomplete_inference_stage",
                    "inference stages require model_id and task"))
            else:
                row = store.models.get(st.model_id)
                if row is None:
                    issues.append(_issue(
                        f"{path}.model_id", "unknown_model",
                        f"model {st.model_id!r} is not registered"))
                else:
                    runtime = model_runtime(store, row)
                    if not runtime["enabled"] or not runtime["available"]:
                        issues.append(_issue(
                            f"{path}.model_id", "model_unavailable",
                            f"model {st.model_id!r} is not currently available"))
                    if st.task not in runtime["tasks"]:
                        issues.append(_issue(
                            f"{path}.task", "unsupported_task",
                            f"task {st.task!r} is not supported by model {st.model_id!r}"))
                    if st.options and st.options.get("engine_options"):
                        adapter = ENGINE_REGISTRY.get(runtime["engine_id"])
                        if adapter is not None:
                            for e in adapter.validate_engine_options(st.options["engine_options"]):
                                issues.append(_issue(f"{path}.options.engine_options",
                                                     "invalid_engine_option", e))

        if st.kind == "tracker":
            if not any(seen[r].kind == "inference" for r in (st.inputs or []) if r in seen):
                issues.append(_issue(
                    path, "tracker_without_inference",
                    "tracker stages require at least one inference input"))

        if st.kind == "filter":
            if st.portable is None or st.portable.filter is None:
                issues.append(_issue(
                    path, "missing_filter_spec",
                    "filter stages must set portable.filter"))

        # presentation-phase isolation: may not feed inference stages
        # (checked when the inference stage's inputs are validated below)

        # portable options: kind whitelists + parameter validation
        if st.portable is not None:
            for opt_name in ("filter", "gate", "annotation", "video"):
                if getattr(st.portable, opt_name) is None:
                    continue
                if opt_name not in _PORTABLE_KINDS[st.kind]:
                    issues.append(_issue(
                        f"{path}.portable", "portable_option_wrong_kind",
                        f"portable.{opt_name} is not valid for kind {st.kind!r}"))
                    continue
                if opt_name == "filter":
                    issues += _check_filter_params(f"{path}.portable.filter",
                                                   st.portable.filter)
                if opt_name == "gate":
                    gate = st.portable.gate
                    ref = seen.get(gate.motion_stage_id)
                    if ref is None:
                        issues.append(_issue(
                            f"{path}.portable.gate.motion_stage_id",
                            "invalid_stage_input",
                            "motion_stage_id must reference an earlier stage"))
                    elif ref.kind != "filter" or ref.portable is None \
                            or ref.portable.filter is None \
                            or ref.portable.filter.type != "motion":
                        issues.append(_issue(
                            f"{path}.portable.gate.motion_stage_id",
                            "gate_requires_motion_stage",
                            "motion_stage_id must reference a motion filter stage"))

        seen.setdefault(st.id, st)

    # presentation isolation: no presentation-phase stage may feed an
    # inference stage (directly or transitively)
    by_id = {s.id: s for s in stages}

    def is_presentation(stage_id: str, _depth=0) -> bool:
        if _depth > len(by_id):
            return False
        st = by_id.get(stage_id)
        if st is None:
            return False
        if st.phase == "presentation":
            return True
        return any(is_presentation(r, _depth + 1) for r in (st.inputs or []))

    for idx, st in enumerate(stages):
        if st.kind == "inference":
            for ref in st.inputs or []:
                if is_presentation(ref):
                    issues.append(_issue(
                        f"stages[{idx}].inputs", "presentation_feeds_inference",
                        f"inference stage input {ref!r} depends on a presentation-phase stage"))

    return issues

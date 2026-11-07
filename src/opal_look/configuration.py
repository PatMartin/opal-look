"""v1.5 portable configuration: export / validate / import (step 24).

Export produces logical desired state only: sources carry
`redacted_locator` (never a usable URI), no credentials, no runtime
state (media/observations/jobs/recordings/sessions). Import is
atomic under If-Match in one transaction; redacted locators resolve
through `source_bindings` (or an existing source with the same id) —
a `redacted_locator` marker is never imported as a real URI.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .errors import ApiError
from .settings import effective_settings
from .sources import redact_locator
from .timeutil import now_iso

_REDACTED_SENTINEL = "redacted_locator"
_EXPORT_FORMAT_VERSION = "1.0.0"


def _settings_apply(store, data: dict[str, Any]) -> None:
    """Replace settings overrides with imported values — validated before any
    write so a bad bundle can never poison effective_settings (strict model:
    floats for int keys, unknown keys and nulls are all rejected)."""
    from .settings import ServiceSettingsPatch

    try:
        validated = ServiceSettingsPatch.model_validate(data or {})
    except Exception as exc:
        raise ApiError(422, "Invalid settings section in configuration bundle.",
                       details={"error": str(exc)})
    for key, value in validated.model_dump(exclude_unset=True).items():
        store.settings.set(key, value)


def build_export(store) -> dict[str, Any]:
    """PortableConfiguration: logical config only, secrets redacted."""
    sources = []
    for row in store.sources.list():
        sources.append({
            "id": row["source_id"], "kind": row["type"], "name": row["name"],
            "enabled": bool(row["enabled"]),
            "redacted_locator": redact_locator(row["type"], row["locator"]),
            "options": json.loads(row["source_options"] or "{}"),
        })
    models = []
    for row in store.models.list():
        models.append({
            "id": row["model_id"], "name": row["name"],
            "engine_id": row["engine_id"],
            "resource": json.loads(row["resource"] or "{}"),
            "enabled": bool(row["enabled"]),
            "tasks": json.loads(row["tasks"] or "[]"),
            "options": json.loads(row["options"] or "{}"),
        })
    pipelines = []
    for row in store.pipelines.list():
        stages = json.loads(row["stages"] or "[]")
        if not stages and row["model_id"] is not None:
            stages = [{"id": "inference", "kind": "inference",
                       "model_id": row["model_id"], "task": row["task"]}]
        pipelines.append({
            "id": row["pipeline_id"], "name": row["name"],
            "description": row["description"],
            "stages": stages,
        })
    monitors = []
    for row in store.monitors.list():
        monitors.append({
            "id": row["monitor_id"], "name": row["name"],
            "source_id": row["source_id"], "pipeline_id": row["pipeline_id"],
            "enabled": bool(row["enabled"]),
            "restart_policy": row["restart_policy"],
            "options": json.loads(row["options"] or "null"),
            "retention": json.loads(row["retention"] or "null"),
            "profile_id": (row["profile_id"] if "profile_id" in row.keys()
                           else None),
        })
    engines = []
    for row in store.engines.list():
        engines.append({
            "engine_id": row["engine_id"], "name": row["name"],
            "enabled": bool(row["enabled"]),
            "options": json.loads(row["config"] or "{}"),
        })
    return {
        "format_version": _EXPORT_FORMAT_VERSION,
        "exported_at": now_iso(),
        "settings": effective_settings(store).model_dump(mode="json"),
        "engines": engines,
        "profiles": [
            {**json.loads(r["data"] or "{}"),
             "id": r["profile_id"], "name": r["name"],
             "is_active": bool(r["active"])}
            for r in store.profiles.list()
        ],
        "models": models,
        "sources": sources,
        "pipelines": pipelines,
        "zones": [
            {"id": z["zone_id"], "source_id": z["source_id"],
             "name": z["name"], "kind": z["kind"],
             "points": json.loads(z["points"]),
             "enabled": bool(z["enabled"])}
            for z in store.zones.list()
        ],
        "rules": [
            {"id": r["rule_id"], "name": r["name"],
             "source_id": r["source_id"], "zone_id": r["zone_id"],
             "kind": r["kind"],
             "class_filters": json.loads(r["class_filters"] or "[]"),
             "threshold": r["threshold"],
             "minimum_duration_ms": r["minimum_duration_ms"],
             "cooldown_ms": r["cooldown_ms"],
             "enabled": bool(r["enabled"]),
             "capture_on_match": bool(r["capture_on_match"]),
             "clip_on_match": bool(r["clip_on_match"])}
            for r in store.rules.list()
        ],
        "monitors": monitors,
    }


def _issue(path: str, message: str, code: str = "invalid",
           severity: str = "error") -> dict[str, Any]:
    return {"path": path, "code": code, "message": message,
            "severity": severity}


def validate_configuration(store, config: dict[str, Any],
                           bindings: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Concrete issues for a PortableConfiguration (non-mutating)."""
    issues: list[dict[str, Any]] = []
    bindings = bindings or {}

    model_ids = {m.get("id") or m.get("model_id") for m in config.get("models", [])}
    pipeline_ids = {p.get("id") for p in config.get("pipelines", [])}
    source_ids = {s.get("id") for s in config.get("sources", [])}
    zone_ids: set = {z.get("id") for z in config.get("zones", [])}

    settings = config.get("settings") or {}
    if settings:
        from .settings import ServiceSettingsPatch
        try:
            ServiceSettingsPatch.model_validate(settings)
        except Exception as exc:
            issues.append(_issue("settings",
                                 f"invalid settings values: {exc}"))
    dp = settings.get("default_pipeline_id")
    if dp and dp not in pipeline_ids:
        issues.append(_issue("settings.default_pipeline_id",
                             f"default pipeline {dp!r} not in configuration"))

    for i, m in enumerate(config.get("models", [])):
        ref = m.get("resource_ref") or ""
        if "://" in ref and "@" in ref.split("://", 1)[1].split("/", 1)[0]:
            issues.append(_issue(f"models[{i}].resource_ref",
                                 "resource_ref embeds credentials"))
    for i, p in enumerate(config.get("pipelines", [])):
        stages = p.get("stages") or []
        if not stages and p.get("model_id") not in model_ids:
            issues.append(_issue(f"pipelines[{i}].model_id",
                                 f"model {p.get('model_id')!r} not in configuration"))
        for j, st in enumerate(stages):
            if st.get("kind") == "inference" and st.get("model_id") not in model_ids:
                issues.append(_issue(f"pipelines[{i}].stages[{j}].model_id",
                                     f"model {st.get('model_id')!r} not in configuration"))
    for i, s in enumerate(config.get("sources", [])):
        loc = s.get("redacted_locator")
        sid = s.get("id")
        b = bindings.get(sid)
        existing = store.sources.get(sid) if sid else None
        if b is None and existing is None:
            issues.append(_issue(
                f"sources[{i}].redacted_locator",
                f"source {sid!r} has no import binding; supply "
                f"source_bindings[{sid!r}].locator or import over an "
                "existing source with the same id", code="unresolved_binding"))
    for i, z in enumerate(config.get("zones", [])):
        if z.get("source_id") not in source_ids:
            issues.append(_issue(f"zones[{i}].source_id",
                                 f"source {z.get('source_id')!r} not in configuration"))
        if z.get("kind") == "polygon" and len(z.get("points", [])) < 3:
            issues.append(_issue(f"zones[{i}].points",
                                 "polygon zones require >=3 points"))
    for i, r in enumerate(config.get("rules", [])):
        if r.get("source_id") not in source_ids:
            issues.append(_issue(f"rules[{i}].source_id",
                                 f"source {r.get('source_id')!r} not in configuration"))
        zid = r.get("zone_id")
        if zid and zid not in zone_ids:
            issues.append(_issue(f"rules[{i}].zone_id",
                                 f"zone {zid!r} not in configuration"))
    for i, mon in enumerate(config.get("monitors", [])):
        if mon.get("source_id") not in source_ids:
            issues.append(_issue(f"monitors[{i}].source_id",
                                 f"source {mon.get('source_id')!r} not in configuration"))
        if mon.get("pipeline_id") not in pipeline_ids:
            issues.append(_issue(f"monitors[{i}].pipeline_id",
                                 f"pipeline {mon.get('pipeline_id')!r} not in configuration"))
        pid = mon.get("profile_id")
        if pid is not None and store.profiles.get(pid) is None \
                and not any(p.get("id") == pid for p in config.get("profiles", [])):
            issues.append(_issue(f"monitors[{i}].profile_id",
                                 f"profile {pid!r} not in configuration"))
    return issues


def apply_import(store, request, config: dict[str, Any],
                 bindings: dict[str, Any] | None) -> None:
    """Atomic replace under If-Match. Caller holds write_txn? No —
    this function owns its own validation-then-swap inside one txn."""
    issues = validate_configuration(store, config, bindings)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        raise ApiError(422, "Configuration is invalid: "
                            + "; ".join(i["message"] for i in errors[:4]),
                       details={"issues": issues})

    # incompatible running work prevents a safe swap (jobs/recordings only;
    # monitors are config and are stopped + recreated by the swap itself)
    running_jobs = store.jobs.count_nonterminal()
    active_recs = store.recordings.count_active()
    if running_jobs or active_recs:
        raise ApiError(409, "Incompatible running work prevents a safe "
                            f"swap ({running_jobs} jobs, {active_recs} "
                            "recordings).")

    bindings = bindings or {}
    src_rows: dict[str, sqlite3.Row] = {r["source_id"]: r for r in store.sources.list()}
    for s in config.get("sources", []):
        sid = s["id"]
        existing = src_rows.get(sid)
        if sid in bindings:
            s["_locator"] = bindings[sid].get("locator")
            s["_credential_ref"] = bindings[sid].get("secret_ref")
        elif existing is not None:
            s["_locator"] = existing["locator"]
            s["_credential_ref"] = existing["credential_ref"]
        else:
            raise ApiError(422, f"Unresolved locator binding for source "
                                f"{sid!r}.", details={"issues": issues})

    # stop monitor workers for replaced monitors before the swap
    for mid, rt in list(getattr(request.app.state, "monitor_runtimes", {}).items()):
        rt.stop()
        request.app.state.monitor_runtimes.pop(mid, None)

    for row in store.monitors.list():
        store.monitors.delete(row["monitor_id"])
    for row in store.sources.list():
        store.sources.delete(row["source_id"])
    store.rules.delete_all()
    store.zones.delete_all()
    for row in store.pipelines.list():
        store.pipelines.delete(row["pipeline_id"])
    for row in store.models.list():
        store.models.delete(row["model_id"])
    for row in store.profiles.list():
        store.profiles.delete(row["profile_id"])

    for e in config.get("engines", []):
        eid = e.get("engine_id") or e.get("id")
        if eid and store.engines.get(eid) is not None:
            fields = {"enabled": 1 if e.get("enabled", True) else 0}
            if e.get("options") is not None:
                fields["config"] = e["options"]
            store.engines.update(eid, fields)
    for m in config.get("models", []):
        store.models.insert(
            m["id"], m.get("name", m["id"]), m["engine_id"],
            m.get("resource") or {}, bool(m.get("enabled", True)),
            m.get("tasks"), m.get("options"), m.get("resource_ref"))
    for s in config.get("sources", []):
        store.sources.insert({
            "source_id": s["id"], "name": s.get("name", s["id"]),
            "type": s["kind"], "locator": s["_locator"],
            "credential_ref": s.get("_credential_ref"),
            "enabled": 1 if s.get("enabled", True) else 0,
            "source_options": json.dumps(s.get("options") or {}),
            "zones": [],
        })
    for z in config.get("zones", []):
        store.zones.insert({
            "zone_id": z["id"], "source_id": z["source_id"],
            "name": z.get("name", z["id"]), "kind": z.get("kind", "polygon"),
            "points": z.get("points") or [],
            "enabled": bool(z.get("enabled", True)),
        })
    for r in config.get("rules", []):
        store.rules.insert({
            "rule_id": r["id"], "source_id": r["source_id"],
            "zone_id": r.get("zone_id"), "name": r.get("name", r["id"]),
            "kind": r.get("kind", "object_appears"),
            "class_filters": r.get("class_filters"),
            "threshold": r.get("threshold"),
            "minimum_duration_ms": r.get("minimum_duration_ms"),
            "cooldown_ms": r.get("cooldown_ms"),
            "enabled": bool(r.get("enabled", True)),
            "capture_on_match": bool(r.get("capture_on_match")),
            "clip_on_match": bool(r.get("clip_on_match")),
        })
    for p in config.get("pipelines", []):
        store.pipelines.insert({
            "pipeline_id": p["id"], "name": p.get("name", p["id"]),
            "description": p.get("description"),
            "model_id": p.get("model_id"), "task": p.get("task"),
            "stages": p.get("stages") or [],
            "options": p.get("options") or {},
            "retention": p.get("retention") or {},
        })
    for p in config.get("profiles", []):
        pid = p.get("id")
        data = {k: v for k, v in p.items() if k not in ("id", "is_active")}
        if isinstance(pid, int):
            store.profiles.insert_kernel_explicit(
                {"profile_id": pid, "name": data.pop("name", str(pid)),
                 "is_active": bool(p.get("is_active")), "data": data})
        else:
            store.profiles.insert_kernel(
                {"name": data.pop("name", "profile"),
                 "is_active": bool(p.get("is_active")), "data": data})
    for mon in config.get("monitors", []):
        store.monitors.insert({
            "monitor_id": mon["id"], "name": mon.get("name", mon["id"]),
            "source_id": mon["source_id"], "pipeline_id": mon["pipeline_id"],
            "enabled": 1 if mon.get("enabled", True) else 0,
            "restart_policy": mon.get("restart_policy", "on_failure"),
            "options": json.dumps(mon.get("options")),
            "retention": json.dumps(mon.get("retention")),
            "conditions": "[]",
            "publish_events": 0,
            "created_at": now_iso(),
        })
    if "settings" in config:
        _settings_apply(store, config["settings"])

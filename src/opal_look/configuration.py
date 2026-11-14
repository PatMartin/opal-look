"""Portable configuration: export / validate / import.

Export produces logical desired state only — settings, engine config and
profiles; no credentials, no runtime state. Import is atomic under
If-Match in one transaction.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import ApiError
from .settings import effective_settings
from .timeutil import now_iso

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
    """OpalConfigExport: logical config only, secrets redacted."""
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
    }


def _issue(path: str, message: str, code: str = "invalid",
           severity: str = "error") -> dict[str, Any]:
    return {"path": path, "code": code, "message": message,
            "severity": severity}


def validate_configuration(store, config: dict[str, Any],
                           bindings: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Concrete issues for an OpalConfigExport (non-mutating)."""
    issues: list[dict[str, Any]] = []

    settings = config.get("settings") or {}
    if settings:
        from .settings import ServiceSettingsPatch
        try:
            ServiceSettingsPatch.model_validate(settings)
        except Exception as exc:
            issues.append(_issue("settings",
                                 f"invalid settings values: {exc}"))

    from .engines import ENGINE_REGISTRY
    known_engines = {e.engine_id for e in ENGINE_REGISTRY.all()}
    for i, e in enumerate(config.get("engines", [])):
        eid = e.get("engine_id") or e.get("id")
        if eid and eid not in known_engines:
            issues.append(_issue(f"engines[{i}].engine_id",
                                 f"unknown engine {eid!r}",
                                 severity="warning"))

    for i, p in enumerate(config.get("profiles", [])):
        if not p.get("name"):
            issues.append(_issue(f"profiles[{i}].name", "name is required"))
    return issues


def apply_import(store, request, config: dict[str, Any],
                 bindings: dict[str, Any] | None) -> None:
    """Atomic replace under If-Match. Caller holds write_txn."""
    issues = validate_configuration(store, config, bindings)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        raise ApiError(422, "Configuration is invalid: "
                            + "; ".join(i["message"] for i in errors[:4]),
                       details={"issues": issues})

    for e in config.get("engines", []):
        eid = e.get("engine_id") or e.get("id")
        if eid and store.engines.get(eid) is not None:
            fields = {"enabled": 1 if e.get("enabled", True) else 0}
            if e.get("options") is not None:
                fields["config"] = e["options"]
            store.engines.update(eid, fields)
    for row in store.profiles.list():
        store.profiles.delete(row["profile_id"])
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
    if "settings" in config:
        _settings_apply(store, config["settings"])

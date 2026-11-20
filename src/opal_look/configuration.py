"""Portable configuration snapshots (kernel OpalConfigSnapshot).

`config save` captures persistent desired configuration - settings
overrides plus the declared resources sections (profiles, personas,
engines, models) - into a closed-envelope snapshot. `config load`
atomically replaces that state under If-Match after validating the
whole candidate; it executes no actions (no model loads, no restarts).
The `models` section has no live persistence here (models are
engine-federated), so it is persisted verbatim as desired state and
round-tripped through save/load. `config validate` runs the same checks
without mutating anything.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import ApiError
from .personas import PERSONA_ID_RE, persona_read
from .profiles import OWN_COMPARTMENT, profile_read
from .timeutil import now_iso

MODULE_ID = "opal-look"
SNAPSHOT_FORMAT = "1.0.0"
RESOURCE_SECTIONS = frozenset({"profiles", "personas", "engines", "models"})
ENVELOPE_FIELDS = frozenset(
    {"format_version", "module", "created_at", "settings", "resources"})

_MANAGED_KEY = "managed_snapshot"
_MODELS_KEY = "desired_models"


def _issue(code: str, path: str, message: str) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message}


def build_snapshot(store) -> dict[str, Any]:
    """OpalConfigSnapshot of the live persistent configuration."""
    engines = [
        {
            "engine_id": row["engine_id"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "options": json.loads(row["config"] or "{}"),
        }
        for row in store.engines.list()
    ]
    return {
        "format_version": SNAPSHOT_FORMAT,
        "module": MODULE_ID,
        "created_at": now_iso(),
        "settings": dict(store.settings.overrides()),
        "resources": {
            "profiles": [profile_read(r) for r in store.profiles.list()],
            "personas": [persona_read(r) for r in store.personas.list()],
            "engines": engines,
            "models": json.loads(store.meta.get(_MODELS_KEY) or "[]"),
        },
    }


def save_managed(store, snapshot: dict[str, Any]) -> None:
    """Atomically create or replace the single default managed snapshot."""
    with store.write_txn():
        store.meta.set(_MANAGED_KEY, json.dumps(snapshot))


def load_managed(store) -> dict[str, Any] | None:
    raw = store.meta.get(_MANAGED_KEY)
    return json.loads(raw) if raw is not None else None


def validate_snapshot(store, snapshot: Any, registry
                      ) -> tuple[list[dict], list[dict]]:
    """(errors, warnings) for one candidate snapshot - non-mutating.

    Loose-typed so malformed envelopes surface as structured issues."""
    errors: list[dict] = []
    warnings: list[dict] = []
    if not isinstance(snapshot, dict):
        errors.append(_issue("invalid_envelope", "",
                             "Snapshot must be a JSON object."))
        return errors, warnings

    extra = set(snapshot) - ENVELOPE_FIELDS
    if extra:
        errors.append(_issue("invalid_envelope", "",
                             f"Unknown snapshot fields: {sorted(extra)}."))
    version = snapshot.get("format_version")
    if version != SNAPSHOT_FORMAT:
        errors.append(_issue("unsupported_version", "format_version",
                             f"Unsupported snapshot format_version {version!r}; "
                             f"this contract accepts {SNAPSHOT_FORMAT!r}."))
    module = snapshot.get("module")
    if module != MODULE_ID:
        errors.append(_issue("wrong_module", "module",
                             f"Snapshot is for module {module!r}; this service "
                             f"is {MODULE_ID!r}."))
    if not isinstance(snapshot.get("created_at"), str):
        errors.append(_issue("invalid_envelope", "created_at",
                             "created_at is required and must be a string."))

    _validate_settings(snapshot.get("settings"), errors)
    _validate_resources(store, snapshot.get("resources"), registry,
                        errors, warnings)
    return errors, warnings


def _validate_settings(settings: Any, errors: list[dict]) -> None:
    from .settings import SETTINGS_KEYS, ServiceSettingsPatch

    if not isinstance(settings, dict):
        errors.append(_issue("invalid_envelope", "settings",
                             "settings is required and must be an object."))
        return
    for key, value in settings.items():
        if key not in SETTINGS_KEYS:
            errors.append(_issue("unknown_setting", f"settings.{key}",
                                 f"Unknown setting key {key!r}."))
            continue
        try:
            ServiceSettingsPatch.model_validate({key: value})
        except Exception as exc:
            errors.append(_issue("invalid_setting", f"settings.{key}",
                                 f"Invalid value for {key!r}: {exc}"))


def _validate_resources(store, resources: Any, registry,
                        errors: list[dict], warnings: list[dict]) -> None:
    if not isinstance(resources, dict):
        errors.append(_issue("invalid_envelope", "resources",
                             "resources is required and must be an object."))
        return
    unknown = set(resources) - RESOURCE_SECTIONS
    for section in sorted(unknown):
        errors.append(_issue("unknown_section", f"resources.{section}",
                             f"Unknown resources section {section!r}."))

    _validate_profiles(resources.get("profiles"), errors)
    _validate_personas(resources.get("personas"), errors)
    _validate_engines(resources.get("engines"), registry, errors, warnings)
    if resources.get("models") is not None and \
            not isinstance(resources["models"], list):
        errors.append(_issue("invalid_resource", "resources.models",
                             "models must be an array."))


def _validate_profiles(profiles: Any, errors: list[dict]) -> None:
    if profiles is None:
        return
    if not isinstance(profiles, list):
        errors.append(_issue("invalid_resource", "resources.profiles",
                             "profiles must be an array."))
        return
    seen, actives = set(), []
    for i, p in enumerate(profiles):
        path = f"resources.profiles[{i}]"
        if not isinstance(p, dict):
            errors.append(_issue("invalid_resource", path,
                                 "Profile must be an object."))
            continue
        if not isinstance(p.get("name"), str) or not p["name"]:
            errors.append(_issue("invalid_resource", f"{path}.name",
                                 "name is required."))
        pid = p.get("id")
        if pid is not None:
            if not isinstance(pid, str) or not pid:
                errors.append(_issue("invalid_resource", f"{path}.id",
                                     "id must be a non-empty string."))
            elif pid in seen:
                errors.append(_issue("invalid_resource", f"{path}.id",
                                     f"Duplicate profile id {pid!r}."))
            else:
                seen.add(pid)
        if p.get("is_active"):
            actives.append(pid)
        for key in ("shared", "modules"):
            if key in p and not isinstance(p[key], dict):
                errors.append(_issue("invalid_resource", f"{path}.{key}",
                                     f"{key} must be an object."))
        if isinstance(p.get("shared"), dict) and p["shared"]:
            errors.append(_issue("invalid_resource", f"{path}.shared",
                                 "shared declares no fields."))
        modules = p.get("modules")
        if isinstance(modules, dict):
            own = modules.get(OWN_COMPARTMENT)
            if own is not None and own != {}:
                errors.append(_issue(
                    "invalid_resource", f"{path}.modules.{OWN_COMPARTMENT}",
                    "opal-look compartment declares no fields."))
    if len(actives) > 1:
        errors.append(_issue("invalid_resource", "resources.profiles",
                             "At most one profile may be marked is_active."))


def _validate_personas(personas: Any, errors: list[dict]) -> None:
    if personas is None:
        return
    if not isinstance(personas, list):
        errors.append(_issue("invalid_resource", "resources.personas",
                             "personas must be an array."))
        return
    for i, p in enumerate(personas):
        path = f"resources.personas[{i}]"
        if not isinstance(p, dict):
            errors.append(_issue("invalid_resource", path,
                                 "Persona must be an object."))
            continue
        pid = p.get("persona_id")
        if not isinstance(pid, str) or not PERSONA_ID_RE.match(pid):
            errors.append(_issue("invalid_resource", f"{path}.persona_id",
                                 "persona_id must match "
                                 "^[A-Za-z0-9][A-Za-z0-9._-]*$."))
        if not isinstance(p.get("name"), str) or not p["name"]:
            errors.append(_issue("invalid_resource", f"{path}.name",
                                 "name is required."))
        if "enabled" in p and not isinstance(p["enabled"], bool):
            errors.append(_issue("invalid_resource", f"{path}.enabled",
                                 "enabled must be a boolean."))


def _validate_engines(engines: Any, registry,
                      errors: list[dict], warnings: list[dict]) -> None:
    if engines is None:
        return
    if not isinstance(engines, list):
        errors.append(_issue("invalid_resource", "resources.engines",
                             "engines must be an array."))
        return
    known = {a.engine_id for a in registry.all()}
    for i, e in enumerate(engines):
        path = f"resources.engines[{i}]"
        if not isinstance(e, dict) or not isinstance(e.get("engine_id"), str):
            errors.append(_issue("invalid_resource", f"{path}.engine_id",
                                 "engine_id is required."))
            continue
        if e["engine_id"] not in known:
            warnings.append(_issue(
                "unknown_engine", f"{path}.engine_id",
                f"Engine {e['engine_id']!r} is not registered here; "
                "entry is preserved but not applied."))
        if "options" in e and not isinstance(e["options"], dict):
            errors.append(_issue("invalid_resource", f"{path}.options",
                                 "options must be an object."))


def apply_snapshot(store, snapshot: dict[str, Any], registry) -> list[str]:
    """Atomically replace persistent configuration. Caller holds write_txn
    and has already run validate_snapshot; returns pending_restart_fields."""
    from .settings import ServiceSettingsPatch

    settings = snapshot["settings"]
    for key in list(store.settings.overrides()):
        store.settings.delete(key)
    validated = ServiceSettingsPatch.model_validate(settings)
    for key, value in validated.model_dump(exclude_unset=True).items():
        store.settings.set(key, value)

    resources = snapshot["resources"]
    known = {a.engine_id for a in registry.all()}
    for e in resources.get("engines") or []:
        if e["engine_id"] not in known:
            continue
        fields: dict[str, Any] = {}
        if "enabled" in e:
            fields["enabled"] = 1 if e["enabled"] else 0
        if "options" in e:
            fields["config"] = e["options"]
        if fields:
            store.engines.update(e["engine_id"], fields)

    store.profiles.delete_all()
    active = None
    for p in resources.get("profiles") or []:
        pid = p.get("id") or f"p-{__import__('secrets').token_hex(6)}"
        store.profiles.insert({
            "profile_id": str(pid),
            "name": p["name"],
            "description": p.get("description"),
            "is_active": False,
            "shared": p.get("shared") or {},
            "modules": p.get("modules") or {},
            "created_at": p.get("created_at"),
            "updated_at": p.get("updated_at"),
        })
        if p.get("is_active"):
            active = str(pid)
    if active is not None:
        store.profiles.set_active(active)

    store.personas.delete_all()
    for p in resources.get("personas") or []:
        store.personas.insert({
            "persona_id": p["persona_id"],
            "name": p["name"],
            "description": p.get("description"),
            "voice_id": p.get("voice_id"),
            "enabled": p.get("enabled", True),
            "origin": p.get("origin") or "local",
            "created_at": p.get("created_at"),
            "updated_at": p.get("updated_at"),
        })

    if "models" in resources:
        store.meta.set(_MODELS_KEY, json.dumps(resources["models"]))
    return []

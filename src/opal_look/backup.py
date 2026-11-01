"""ConfigExport export/import/validate + server-managed backup files."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .engines import ENGINE_REGISTRY
from .errors import ApiError
from .schemas import AnalysisSettings, ModelCreate, SourceCreate
from .settings import ServiceSettings, effective_settings
from .sources import check_locator
from .store import Store
from .timeutil import iso, now_iso

_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def export_config(store: Store) -> dict[str, Any]:
    return {
        "version": "1.1.0",
        "exported_at": now_iso(),
        "engines": [
            {"engine_id": r["engine_id"], "enabled": bool(r["enabled"]),
             "config": json.loads(r["config"])}
            for r in store.engines.list()
        ],
        "models": [
            {"model_id": r["model_id"], "name": r["name"], "engine_id": r["engine_id"],
             "resource": json.loads(r["resource"]), "enabled": bool(r["enabled"])}
            for r in store.models.list()
        ],
        "sources": [
            {"source_id": r["source_id"], "name": r["name"], "type": r["type"],
             "locator": r["locator"], "credential_ref": r["credential_ref"],
             "enabled": bool(r["enabled"]),
             "source_options": json.loads(r["source_options"])}
            for r in store.sources.list()
        ],
        "profiles": [
            {"profile_id": r["profile_id"], "name": r["name"], "model_id": r["model_id"],
             "task": r["task"], "settings": json.loads(r["settings"]),
             "active": bool(r["active"])}
            for r in store.profiles.list()
        ],
        "settings": effective_settings(store).model_dump(),
    }


def validate_config(store: Store, payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Semantic (non-structural) validation of a ConfigExport payload."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        ServiceSettings.model_validate(payload.get("settings") or {})
    except Exception as exc:
        errors.append(f"settings: {exc}")

    for e in payload.get("engines") or []:
        eid = e.get("engine_id")
        adapter = ENGINE_REGISTRY.get(eid) if eid else None
        if adapter is None:
            errors.append(f"engine {eid!r} is not installed")
        else:
            errors.extend(adapter.validate_engine_options(e.get("config") or {}))

    model_ids: set[str] = set()
    model_tasks: dict[str, list[str]] = {}
    for m in payload.get("models") or []:
        try:
            mc = ModelCreate.model_validate(m)
        except Exception as exc:
            errors.append(f"model: {exc}")
            continue
        if mc.model_id in model_ids:
            errors.append(f"duplicate model_id {mc.model_id!r}")
        model_ids.add(mc.model_id)
        adapter = ENGINE_REGISTRY.get(mc.engine_id)
        if adapter is None:
            errors.append(f"model {mc.model_id!r}: engine {mc.engine_id!r} not installed")
        else:
            e2, _ = adapter.validate_model(mc.resource)
            errors.extend(f"model {mc.model_id!r}: {x}" for x in e2)
            model_tasks[mc.model_id] = adapter.describe_model(mc.resource)["tasks"]

    source_ids: set[str] = set()
    for s in payload.get("sources") or []:
        try:
            sc = SourceCreate.model_validate(s)
        except Exception as exc:
            errors.append(f"source: {exc}")
            continue
        if sc.source_id in source_ids:
            errors.append(f"duplicate source_id {sc.source_id!r}")
        source_ids.add(sc.source_id)
        errors.extend(f"source {sc.source_id!r}: {x}"
                      for x in check_locator(sc.type, sc.locator))
        if sc.type == "media" and store.media.get(sc.locator) is None:
            warnings.append(f"source {sc.source_id!r}: media {sc.locator!r} unavailable")

    profiles = payload.get("profiles") or []
    pids, actives = set(), 0
    for p in profiles:
        pid = p.get("profile_id")
        if pid in pids:
            errors.append(f"duplicate profile_id {pid}")
        pids.add(pid)
        if p.get("active"):
            actives += 1
        mid = p.get("model_id")
        if mid is not None and mid not in model_ids:
            # Fall back to an existing registered model for partial restores.
            row = store.models.get(mid)
            if row is not None:
                adapter = ENGINE_REGISTRY.get(row["engine_id"])
                tasks = adapter.describe_model(json.loads(row["resource"]))["tasks"]
            else:
                errors.append(f"profile {pid}: unknown model {mid!r}")
                tasks = []
        else:
            tasks = model_tasks.get(mid, [])
        if tasks and p.get("task") is not None and p["task"] not in tasks:
            errors.append(f"profile {pid}: task {p['task']!r} incompatible")
        try:
            AnalysisSettings.model_validate(p.get("settings") or {})
        except Exception as exc:
            errors.append(f"profile {pid}: settings: {exc}")
    if profiles and actives != 1:
        errors.append("exactly one profile must be active")
    return errors, warnings


def import_config(store: Store, payload: dict[str, Any]) -> list[str]:
    """Validate then atomically replace configuration. Raises 422/409."""
    if payload.get("version") not in ("1.0.0", "1.1.0"):
        raise ApiError(422, "Unsupported backup version.")
    if store.sessions.count_nonterminal():
        raise ApiError(409, "Import rejected while sessions are nonterminal.")
    errors, warnings = validate_config(store, payload)
    if errors:
        raise ApiError(422, "Backup is structurally incompatible.", details=errors)
    with store.write_txn():
        store.profiles.delete_all()
        store.models.delete_all()
        store.sources.delete_all()
        for e in payload.get("engines") or []:
            if store.engines.get(e["engine_id"]):
                store.engines.update(
                    e["engine_id"],
                    {"enabled": int(bool(e.get("enabled", True))),
                     "config": json.dumps(e.get("config") or {})})
        for m in payload.get("models") or []:
            store.models.insert(m["model_id"], m["name"], m["engine_id"],
                                m["resource"], bool(m.get("enabled", True)))
        for s in payload.get("sources") or []:
            store.sources.insert({
                "source_id": s["source_id"], "name": s["name"], "type": s["type"],
                "locator": s["locator"], "credential_ref": s.get("credential_ref"),
                "enabled": int(bool(s.get("enabled", True))),
                "source_options": json.dumps(s.get("source_options") or {})})
        for p in payload.get("profiles") or []:
            store.profiles.insert_explicit({
                "profile_id": p["profile_id"], "name": p["name"],
                "model_id": p["model_id"], "task": p["task"],
                "settings": json.dumps(p.get("settings") or {}),
                "active": bool(p.get("active"))})
        svc = ServiceSettings.model_validate(payload.get("settings") or {})
        for key, value in svc.model_dump().items():
            store.settings.set(key, value)
    return warnings


def backup_dir(store: Store) -> Path:
    d = Path(store.data_dir) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def check_backup_filename(name: str) -> None:
    if not _FILENAME_RE.match(name):
        raise ApiError(422, "Invalid backup filename.")


def backup_read(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "filename": path.name,
        "created_at": iso(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
        "size_bytes": stat.st_size,
    }

"""rules table: standalone detection/event conditions scoped to a source."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class RuleRepository(Protocol):
    def list(self) -> list[sqlite3.Row]: ...
    def get(self, rule_id: str) -> sqlite3.Row | None: ...
    def list_for_source(self, source_id: str) -> list[sqlite3.Row]: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, rule_id: str, fields: dict[str, Any]) -> None: ...
    def delete(self, rule_id: str) -> None: ...


class SqliteRuleRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM rules ORDER BY source_id, rule_id").fetchall()

    def get(self, rule_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM rules WHERE rule_id = ?", (rule_id,)).fetchone()

    def list_for_source(self, source_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM rules WHERE source_id = ? ORDER BY rule_id",
            (source_id,)).fetchall()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO rules (rule_id, source_id, zone_id, name, kind, "
            "class_filters, threshold, minimum_duration_ms, cooldown_ms, "
            "enabled, capture_on_match, clip_on_match, last_triggered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fields["rule_id"], fields["source_id"], fields.get("zone_id"),
             fields["name"], fields["kind"],
             json.dumps(fields.get("class_filters") or []),
             fields.get("threshold"), fields.get("minimum_duration_ms"),
             fields.get("cooldown_ms"),
             int(bool(fields.get("enabled", True))),
             int(bool(fields.get("capture_on_match"))),
             int(bool(fields.get("clip_on_match"))),
             fields.get("last_triggered_at")),
        )

    def update(self, rule_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [json.dumps(v) if isinstance(v, (dict, list)) else v
                  for v in fields.values()]
        self._conn.execute(
            f"UPDATE rules SET {assignments} WHERE rule_id = ?",
            (*values, rule_id))

    def delete(self, rule_id: str) -> None:
        self._conn.execute("DELETE FROM rules WHERE rule_id = ?", (rule_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM rules")


def rule_read(row: sqlite3.Row) -> dict[str, Any]:
    """Contract Rule shape."""
    return {
        "id": row["rule_id"],
        "name": row["name"],
        "source_id": row["source_id"],
        "zone_id": row["zone_id"],
        "kind": row["kind"],
        "class_filters": json.loads(row["class_filters"] or "[]"),
        "threshold": row["threshold"],
        "minimum_duration_ms": row["minimum_duration_ms"],
        "cooldown_ms": row["cooldown_ms"],
        "enabled": bool(row["enabled"]),
        "capture_on_match": bool(row["capture_on_match"]),
        "clip_on_match": bool(row["clip_on_match"]),
        "last_triggered_at": row["last_triggered_at"],
    }

"""monitors table: persistent desired-state workers (v1.5)."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol


class MonitorRepository(Protocol):
    def get(self, monitor_id: str) -> sqlite3.Row | None: ...
    def list(self) -> list[sqlite3.Row]: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, monitor_id: str, fields: dict[str, Any]) -> None: ...
    def delete(self, monitor_id: str) -> None: ...
    def bump_revision(self, monitor_id: str) -> int: ...


class SqliteMonitorRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, monitor_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM monitors WHERE monitor_id = ?", (monitor_id,)
        ).fetchone()

    def list(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM monitors ORDER BY created_at, monitor_id").fetchall()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO monitors (monitor_id, name, source_id, pipeline_id, "
            "enabled, restart_policy, options, retention, conditions, "
            "publish_events, created_at, last_observation_at, last_failure, "
            "revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fields["monitor_id"], fields["name"], fields["source_id"],
             fields["pipeline_id"], fields.get("enabled", 1),
             fields.get("restart_policy", "on_failure"),
             fields.get("options", "null"), fields.get("retention", "null"),
             fields.get("conditions", "[]"), fields.get("publish_events", 0),
             fields["created_at"], fields.get("last_observation_at"),
             fields.get("last_failure"), fields.get("revision", 0)))

    def update(self, monitor_id: str, fields: dict[str, Any]) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(
            f"UPDATE monitors SET {cols} WHERE monitor_id = ?",
            (*fields.values(), monitor_id))

    def delete(self, monitor_id: str) -> None:
        self._conn.execute("DELETE FROM monitors WHERE monitor_id = ?",
                           (monitor_id,))

    def bump_revision(self, monitor_id: str) -> int:
        cur = self._conn.execute(
            "UPDATE monitors SET revision = revision + 1 "
            "WHERE monitor_id = ? RETURNING revision", (monitor_id,))
        return cur.fetchone()["revision"]

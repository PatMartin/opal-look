"""zones table: standalone named regions scoped to a source."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class ZoneRepository(Protocol):
    def list(self) -> list[sqlite3.Row]: ...
    def get(self, zone_id: str) -> sqlite3.Row | None: ...
    def list_for_source(self, source_id: str) -> list[sqlite3.Row]: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, zone_id: str, fields: dict[str, Any]) -> None: ...
    def delete(self, zone_id: str) -> None: ...


class SqliteZoneRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM zones ORDER BY source_id, zone_id").fetchall()

    def get(self, zone_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM zones WHERE zone_id = ?", (zone_id,)).fetchone()

    def list_for_source(self, source_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM zones WHERE source_id = ? ORDER BY zone_id",
            (source_id,)).fetchall()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO zones (zone_id, source_id, name, kind, points, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (fields["zone_id"], fields["source_id"], fields["name"],
             fields["kind"], json.dumps(fields["points"]),
             int(bool(fields.get("enabled", True)))),
        )

    def update(self, zone_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [json.dumps(v) if isinstance(v, (dict, list)) else v
                  for v in fields.values()]
        self._conn.execute(
            f"UPDATE zones SET {assignments} WHERE zone_id = ?",
            (*values, zone_id))

    def delete(self, zone_id: str) -> None:
        self._conn.execute("DELETE FROM zones WHERE zone_id = ?", (zone_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM zones")


def zone_read(row: sqlite3.Row) -> dict[str, Any]:
    """Contract Zone shape."""
    return {
        "id": row["zone_id"],
        "source_id": row["source_id"],
        "name": row["name"],
        "kind": row["kind"],
        "points": json.loads(row["points"]),
        "enabled": bool(row["enabled"]),
    }

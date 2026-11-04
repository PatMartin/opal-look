"""sources table: source registrations; availability is probed at read."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class SourceRepository(Protocol):
    def list(self, enabled=None) -> list[sqlite3.Row]: ...
    def get(self, source_id: str) -> sqlite3.Row | None: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, source_id: str, fields: dict[str, Any]) -> None: ...
    def delete(self, source_id: str) -> None: ...
    def count_for_locator(self, locator: str) -> int: ...


class SqliteSourceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self, enabled: bool | None = None) -> list[sqlite3.Row]:
        if enabled is None:
            return self._conn.execute("SELECT * FROM sources ORDER BY rowid").fetchall()
        return self._conn.execute(
            "SELECT * FROM sources WHERE enabled = ? ORDER BY rowid", (int(enabled),)
        ).fetchall()

    def get(self, source_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO sources (source_id, name, type, locator, credential_ref, enabled, source_options, zones) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fields["source_id"],
                fields["name"],
                fields["type"],
                fields["locator"],
                fields.get("credential_ref"),
                int(fields.get("enabled", True)),
                json.dumps(fields.get("source_options") or {}),
                json.dumps(fields.get("zones") or []),
            ),
        )

    def update(self, source_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [_encode(v) for v in fields.values()]
        self._conn.execute(
            f"UPDATE sources SET {assignments} WHERE source_id = ?", (*values, source_id)
        )

    def delete(self, source_id: str) -> None:
        self._conn.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM sources")

    def count_for_locator(self, locator: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM sources WHERE locator = ?", (locator,)
        ).fetchone()["n"]


def _encode(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value

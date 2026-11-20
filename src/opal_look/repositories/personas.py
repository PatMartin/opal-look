"""personas table: the service-local OPAL persona catalog."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol


class PersonaRepository(Protocol):
    def list(self, enabled: bool | None = None) -> list[sqlite3.Row]: ...
    def get(self, persona_id: str) -> sqlite3.Row | None: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, persona_id: str, fields: dict[str, Any]) -> None: ...
    def delete(self, persona_id: str) -> None: ...
    def delete_all(self) -> None: ...


class SqlitePersonaRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self, enabled: bool | None = None) -> list[sqlite3.Row]:
        if enabled is None:
            return self._conn.execute(
                "SELECT * FROM personas ORDER BY persona_id").fetchall()
        return self._conn.execute(
            "SELECT * FROM personas WHERE enabled = ? ORDER BY persona_id",
            (int(enabled),),
        ).fetchall()

    def get(self, persona_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM personas WHERE persona_id = ?", (persona_id,)
        ).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO personas (persona_id, name, description, voice_id, "
            "enabled, origin, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fields["persona_id"], fields["name"],
             fields.get("description"), fields.get("voice_id"),
             int(bool(fields.get("enabled", True))),
             fields.get("origin") or "local",
             fields.get("created_at"), fields.get("updated_at")),
        )

    def update(self, persona_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self._conn.execute(
            f"UPDATE personas SET {assignments} WHERE persona_id = ?",
            (*fields.values(), persona_id),
        )

    def delete(self, persona_id: str) -> None:
        self._conn.execute(
            "DELETE FROM personas WHERE persona_id = ?", (persona_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM personas")

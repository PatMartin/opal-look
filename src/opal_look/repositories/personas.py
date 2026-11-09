"""personas table: named observer identities (v1.6).

A persona binds an optional OPAL Say voice_id for spoken announcements;
this service never validates voice existence locally.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol

from ..timeutil import now_iso


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
            (int(enabled),)).fetchall()

    def get(self, persona_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM personas WHERE persona_id = ?",
            (persona_id,)).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        now = now_iso()
        self._conn.execute(
            "INSERT INTO personas "
            "(persona_id, name, description, voice_id, enabled, "
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fields["persona_id"], fields["name"],
             fields.get("description"), fields.get("voice_id"),
             int(bool(fields.get("enabled", True))), now, now),
        )

    def update(self, persona_id: str, fields: dict[str, Any]) -> None:
        fields = {**fields, "updated_at": now_iso()}
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [int(v) if isinstance(v, bool) else v
                  for v in fields.values()]
        self._conn.execute(
            f"UPDATE personas SET {assignments} WHERE persona_id = ?",
            (*values, persona_id))

    def delete(self, persona_id: str) -> None:
        self._conn.execute(
            "DELETE FROM personas WHERE persona_id = ?", (persona_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM personas")


def persona_read(row: sqlite3.Row) -> dict[str, Any]:
    """Contract PersonaRead shape."""
    return {
        "persona_id": row["persona_id"],
        "name": row["name"],
        "description": row["description"],
        "voice_id": row["voice_id"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

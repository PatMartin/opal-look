"""profiles table: portable namespaced profile documents; at most one active."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class ProfileRepository(Protocol):
    def list(self) -> list[sqlite3.Row]: ...
    def get(self, profile_id: str) -> sqlite3.Row | None: ...
    def get_active(self) -> sqlite3.Row | None: ...
    def count(self) -> int: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, profile_id: str, fields: dict[str, Any]) -> None: ...
    def delete(self, profile_id: str) -> None: ...
    def delete_all(self) -> None: ...
    def set_active(self, profile_id: str) -> None: ...


class SqliteProfileRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM profiles ORDER BY profile_id").fetchall()

    def get(self, profile_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM profiles WHERE profile_id = ?", (profile_id,)
        ).fetchone()

    def count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]

    def get_active(self) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM profiles WHERE active = 1 LIMIT 1"
        ).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO profiles (profile_id, name, description, active, "
            "shared, modules, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fields["profile_id"], fields["name"],
             fields.get("description"),
             int(bool(fields.get("is_active"))),
             json.dumps(fields.get("shared") or {}),
             json.dumps(fields.get("modules") or {}),
             fields.get("created_at"), fields.get("updated_at")),
        )

    def update(self, profile_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [
            json.dumps(v) if isinstance(v, (dict, list)) else v
            for v in fields.values()
        ]
        self._conn.execute(
            f"UPDATE profiles SET {assignments} WHERE profile_id = ?",
            (*values, profile_id),
        )

    def delete(self, profile_id: str) -> None:
        self._conn.execute(
            "DELETE FROM profiles WHERE profile_id = ?", (profile_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM profiles")

    def set_active(self, profile_id: str) -> None:
        """Atomically make one profile active and all others inactive."""
        self._conn.execute(
            "UPDATE profiles SET active = CASE WHEN profile_id = ? THEN 1 ELSE 0 END",
            (profile_id,),
        )

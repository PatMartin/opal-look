"""profiles table: reusable analysis presets; at most one active."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class ProfileRepository(Protocol):
    def list(self) -> list[sqlite3.Row]: ...
    def get(self, profile_id: int) -> sqlite3.Row | None: ...
    def get_active(self) -> sqlite3.Row | None: ...
    def count(self) -> int: ...
    def count_for_model(self, model_id: str) -> int: ...
    def insert(self, name: str, model_id: str, task: str, settings: dict, active: bool) -> int: ...
    def update(self, profile_id: int, fields: dict[str, Any]) -> None: ...
    def delete(self, profile_id: int) -> None: ...
    def set_active(self, profile_id: int) -> None: ...


class SqliteProfileRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM profiles ORDER BY profile_id").fetchall()

    def get(self, profile_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM profiles WHERE profile_id = ?", (profile_id,)
        ).fetchone()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]

    def count_for_model(self, model_id: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM profiles WHERE model_id = ?", (model_id,)
        ).fetchone()["n"]

    def get_active(self) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM profiles WHERE active = 1 LIMIT 1"
        ).fetchone()

    def insert_explicit(self, fields: dict) -> None:
        """Insert preserving profile_id/active (backup import)."""
        self._conn.execute(
            "INSERT INTO profiles (profile_id, name, model_id, task, settings, active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (fields["profile_id"], fields["name"], fields["model_id"], fields["task"],
             fields["settings"], int(fields["active"])),
        )

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM profiles")

    def insert(self, name: str, model_id: str, task: str, settings: dict, active: bool) -> int:
        cursor = self._conn.execute(
            "INSERT INTO profiles (name, model_id, task, settings, active) VALUES (?, ?, ?, ?, ?)",
            (name, model_id, task, json.dumps(settings), int(active)),
        )
        return cursor.lastrowid

    def update(self, profile_id: int, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
        self._conn.execute(
            f"UPDATE profiles SET {assignments} WHERE profile_id = ?", (*values, profile_id)
        )

    def delete(self, profile_id: int) -> None:
        self._conn.execute("DELETE FROM profiles WHERE profile_id = ?", (profile_id,))

    def set_active(self, profile_id: int) -> None:
        """Atomically make one profile active and all others inactive."""
        self._conn.execute(
            "UPDATE profiles SET active = CASE WHEN profile_id = ? THEN 1 ELSE 0 END",
            (profile_id,),
        )

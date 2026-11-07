"""setting_overrides table: per-key JSON overrides over documented defaults."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol

from ..timeutil import now_iso


class SettingsRepository(Protocol):
    def overrides(self) -> dict[str, Any]: ...
    def entry(self, key: str) -> dict[str, Any] | None: ...
    def set(self, key: str, value: Any) -> None: ...
    def delete(self, key: str) -> None: ...


class SqliteSettingsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def overrides(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT key, value FROM setting_overrides").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def entry(self, key: str) -> dict[str, Any] | None:
        """One override with lifecycle metadata, or None when unset."""
        row = self._conn.execute(
            "SELECT value, updated_at FROM setting_overrides WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return {"value": json.loads(row["value"]), "updated_at": row["updated_at"]}

    def set(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO setting_overrides (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value), now_iso()),
        )

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM setting_overrides WHERE key = ?", (key,))

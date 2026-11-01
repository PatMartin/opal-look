"""setting_overrides table: per-key JSON overrides over documented defaults."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class SettingsRepository(Protocol):
    def overrides(self) -> dict[str, Any]: ...
    def set(self, key: str, value: Any) -> None: ...
    def delete(self, key: str) -> None: ...


class SqliteSettingsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def overrides(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT key, value FROM setting_overrides").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def set(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO setting_overrides (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM setting_overrides WHERE key = ?", (key,))

"""engines table: installed adapter registrations (enabled/config only;
capabilities and availability are adapter-probed)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class EngineRepository(Protocol):
    def list(self) -> list[sqlite3.Row]: ...
    def get(self, engine_id: str) -> sqlite3.Row | None: ...
    def seed(self, engine_id: str, name: str, execution: str) -> None: ...
    def update(self, engine_id: str, fields: dict[str, Any]) -> None: ...


class SqliteEngineRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM engines ORDER BY rowid").fetchall()

    def get(self, engine_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM engines WHERE engine_id = ?", (engine_id,)
        ).fetchone()

    def seed(self, engine_id: str, name: str, execution: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO engines (engine_id, name, execution, enabled, config, metadata) "
            "VALUES (?, ?, ?, 1, '{}', '{}')",
            (engine_id, name, execution),
        )

    def update(self, engine_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [_encode(v) for v in fields.values()]
        self._conn.execute(
            f"UPDATE engines SET {assignments} WHERE engine_id = ?", (*values, engine_id)
        )


def _encode(value: Any) -> Any:
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value

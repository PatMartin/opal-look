"""models table: model registrations; adapter-reported fields are probed."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class ModelRepository(Protocol):
    def list(self, engine_id=None, enabled=None) -> list[sqlite3.Row]: ...
    def get(self, model_id: str) -> sqlite3.Row | None: ...
    def insert(self, model_id: str, name: str, engine_id: str, resource: dict, enabled: bool) -> None: ...
    def seed(self, model_id: str, name: str, engine_id: str, resource: dict) -> None: ...
    def update(self, model_id: str, fields: dict[str, Any]) -> None: ...
    def delete(self, model_id: str) -> None: ...


class SqliteModelRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(
        self, engine_id: str | None = None, enabled: bool | None = None
    ) -> list[sqlite3.Row]:
        query = "SELECT * FROM models"
        clauses, params = [], []
        if engine_id is not None:
            clauses.append("engine_id = ?")
            params.append(engine_id)
        if enabled is not None:
            clauses.append("enabled = ?")
            params.append(int(enabled))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        return self._conn.execute(query + " ORDER BY rowid", params).fetchall()

    def get(self, model_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM models WHERE model_id = ?", (model_id,)
        ).fetchone()

    def insert(
        self, model_id: str, name: str, engine_id: str, resource: dict, enabled: bool
    ) -> None:
        self._conn.execute(
            "INSERT INTO models (model_id, name, engine_id, resource, enabled) VALUES (?, ?, ?, ?, ?)",
            (model_id, name, engine_id, json.dumps(resource), int(enabled)),
        )

    def seed(self, model_id: str, name: str, engine_id: str, resource: dict) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO models (model_id, name, engine_id, resource, enabled) "
            "VALUES (?, ?, ?, ?, 1)",
            (model_id, name, engine_id, json.dumps(resource)),
        )

    def update(self, model_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [_encode(v) for v in fields.values()]
        self._conn.execute(
            f"UPDATE models SET {assignments} WHERE model_id = ?", (*values, model_id)
        )

    def delete(self, model_id: str) -> None:
        self._conn.execute("DELETE FROM models WHERE model_id = ?", (model_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM models")


def _encode(value: Any) -> Any:
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value

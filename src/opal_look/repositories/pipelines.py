"""pipelines table: simple (model_id+task) or advanced (stages) definitions."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class PipelineRepository(Protocol):
    def list(self) -> list[sqlite3.Row]: ...
    def get(self, pipeline_id: str) -> sqlite3.Row | None: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, pipeline_id: str, fields: dict[str, Any]) -> None: ...
    def delete(self, pipeline_id: str) -> None: ...


class SqlitePipelineRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM pipelines ORDER BY rowid").fetchall()

    def get(self, pipeline_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM pipelines WHERE pipeline_id = ?", (pipeline_id,)
        ).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        from ..timeutil import now_iso

        self._conn.execute(
            "INSERT INTO pipelines (pipeline_id, name, description, model_id, task, "
            "stages, options, retention, revision, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (
                fields["pipeline_id"], fields["name"], fields.get("description"),
                fields.get("model_id"), fields.get("task"),
                json.dumps(fields.get("stages") or []),
                json.dumps(fields.get("options") or {}),
                json.dumps(fields.get("retention") or {}),
                now_iso(),
            ),
        )

    def update(self, pipeline_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        if assignments:
            assignments += ", "
        assignments += "revision = revision + 1"
        values = [_encode(v) for v in fields.values()]
        self._conn.execute(
            f"UPDATE pipelines SET {assignments} WHERE pipeline_id = ?",
            (*values, pipeline_id),
        )

    def delete(self, pipeline_id: str) -> None:
        self._conn.execute("DELETE FROM pipelines WHERE pipeline_id = ?", (pipeline_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM pipelines")


def _encode(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value

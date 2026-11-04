"""jobs table: finite async work (v1.5)."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol


class JobRepository(Protocol):
    def get(self, job_id: str) -> sqlite3.Row | None: ...
    def list(self, limit: int, cursor: str | None, kind: str | None,
             state: str | None) -> list[sqlite3.Row]: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, job_id: str, fields: dict[str, Any]) -> None: ...
    def count_nonterminal(self) -> int: ...
    def list_state(self, state: str) -> list[sqlite3.Row]: ...


class SqliteJobRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, job_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()

    def list(self, limit=50, cursor=None, kind=None, state=None):
        q = "SELECT * FROM jobs WHERE 1=1"
        params: list = []
        if kind:
            q += " AND kind = ?"
            params.append(kind)
        if state:
            q += " AND state = ?"
            params.append(state)
        if cursor:
            q += " AND (created_at < ? OR (created_at = ? AND job_id < ?))"
            parts = cursor.split("|")
            params.extend([parts[0], parts[0], parts[1]])
        q += " ORDER BY created_at DESC, job_id DESC LIMIT ?"
        params.append(limit + 1)
        return self._conn.execute(q, params).fetchall()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO jobs (job_id, kind, source_id, media_id, "
            "payload_json, state, progress, media_ids, failure, created_at, "
            "started_at, ended_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fields["job_id"], fields["kind"], fields.get("source_id"),
             fields.get("media_id"), fields["payload_json"],
             fields.get("state", "queued"), fields.get("progress", 0.0),
             fields.get("media_ids", "[]"), fields.get("failure"),
             fields["created_at"], fields.get("started_at"),
             fields.get("ended_at")))

    def update(self, job_id: str, fields: dict[str, Any]) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(
            f"UPDATE jobs SET {cols} WHERE job_id = ?",
            (*fields.values(), job_id))

    def count_nonterminal(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE state IN ('queued','running')"
        ).fetchone()["n"]

    def list_state(self, state: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM jobs WHERE state = ?", (state,)).fetchall()

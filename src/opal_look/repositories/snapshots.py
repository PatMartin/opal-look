"""snapshots table: explicitly retained JPEG metadata; bytes on disk."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol


class SnapshotRepository(Protocol):
    def get(self, snapshot_id: str) -> sqlite3.Row | None: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def delete(self, snapshot_id: str) -> None: ...
    def page(self, now: str, result_id: str | None, after: list | None, limit: int) -> list[sqlite3.Row]: ...


class SqliteSnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, snapshot_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO snapshots (snapshot_id, result_id, annotated, path, width, height, "
            "created_at, expires_at, source_id, session_id, observation_id, "
            "frame_time, mime_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fields["snapshot_id"],
                fields.get("result_id", ""),
                int(fields["annotated"]),
                fields["path"],
                fields["width"],
                fields["height"],
                fields["created_at"],
                fields["expires_at"],
                fields.get("source_id"),
                fields.get("session_id"),
                fields.get("observation_id"),
                fields.get("frame_time"),
                fields.get("mime_type"),
            ),
        )

    def delete(self, snapshot_id: str) -> None:
        self._conn.execute("DELETE FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))

    def list_live(self, now: str, source_id: str | None = None) -> list[sqlite3.Row]:
        """Non-expired captures (upstream /captures/ listing)."""
        query = ("SELECT * FROM snapshots WHERE expires_at > ?")
        params: list = [now]
        if source_id is not None:
            query += " AND source_id = ?"
            params.append(source_id)
        query += " ORDER BY created_at DESC, snapshot_id DESC"
        return self._conn.execute(query, params).fetchall()

    def page(
        self, now: str, result_id: str | None, after: list | None, limit: int
    ) -> list[sqlite3.Row]:
        query = "SELECT * FROM snapshots WHERE expires_at > ?"
        params: list = [now]
        if result_id is not None:
            query += " AND result_id = ?"
            params.append(result_id)
        if after is not None:
            query += " AND (created_at < ? OR (created_at = ? AND snapshot_id < ?))"
            params += [after[0], after[0], after[1]]
        query += " ORDER BY created_at DESC, snapshot_id DESC LIMIT ?"
        params.append(limit + 1)
        return self._conn.execute(query, params).fetchall()

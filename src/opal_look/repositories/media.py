"""media table: uploaded image/video registrations; bytes live on disk."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol


class MediaRepository(Protocol):
    def get(self, media_id: str) -> sqlite3.Row | None: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def delete(self, media_id: str) -> None: ...
    def page(self, now: str, after: list | None, limit: int) -> list[sqlite3.Row]: ...


class SqliteMediaRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, media_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM media WHERE media_id = ?", (media_id,)
        ).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO media (media_id, filename, kind, origin, source_id, "
            "job_id, monitor_id, annotated, sha256, content_type, size_bytes, "
            "path, width, height, duration_ms, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fields["media_id"],
                fields["filename"],
                fields["kind"],
                fields.get("origin", "upload"),
                fields.get("source_id"),
                fields.get("job_id"),
                fields.get("monitor_id"),
                fields.get("annotated", 0),
                fields.get("sha256"),
                fields["content_type"],
                fields["size_bytes"],
                fields["path"],
                fields.get("width"),
                fields.get("height"),
                fields.get("duration_ms"),
                fields["created_at"],
                fields["expires_at"],
            ),
        )

    def delete(self, media_id: str) -> None:
        self._conn.execute("DELETE FROM media WHERE media_id = ?", (media_id,))

    def page(self, now: str, after: list | None, limit: int,
             kind: str | None = None, source_id: str | None = None
             ) -> list[sqlite3.Row]:
        """Unexpired media, newest-first with media_id tiebreak."""
        query = "SELECT * FROM media WHERE expires_at > ?"
        params: list = [now]
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind)
        if source_id is not None:
            query += " AND source_id = ?"
            params.append(source_id)
        if after is not None:
            query += " AND (created_at < ? OR (created_at = ? AND media_id < ?))"
            params += [after[0], after[0], after[1]]
        query += " ORDER BY created_at DESC, media_id DESC LIMIT ?"
        params.append(limit + 1)
        return self._conn.execute(query, params).fetchall()

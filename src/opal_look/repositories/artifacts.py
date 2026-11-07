"""artifacts table: produced output files (video/clip/snapshot) as resources."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol


class ArtifactRepository(Protocol):
    def list(self, filters: dict | None = None) -> list[sqlite3.Row]: ...
    def get(self, artifact_id: str) -> sqlite3.Row | None: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def delete(self, artifact_id: str) -> None: ...


class SqliteArtifactRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list(self, filters: dict | None = None) -> list[sqlite3.Row]:
        filters = filters or {}
        query = "SELECT * FROM artifacts WHERE 1=1"
        params: list = []
        for col in ("kind", "source_id", "job_id"):
            if filters.get(col) is not None:
                query += f" AND {col} = ?"
                params.append(filters[col])
        query += " ORDER BY created_at DESC, artifact_id DESC"
        return self._conn.execute(query, params).fetchall()

    def get(self, artifact_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (artifact_id,)).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO artifacts (artifact_id, kind, mime_type, size_bytes, "
            "created_at, expires_at, source_id, job_id, path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fields["artifact_id"], fields["kind"], fields["mime_type"],
             fields["size_bytes"], fields["created_at"], fields["expires_at"],
             fields.get("source_id"), fields.get("job_id"), fields["path"]))

    def delete(self, artifact_id: str) -> None:
        self._conn.execute(
            "DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))


def artifact_read(row: sqlite3.Row) -> dict[str, Any]:
    """Contract Artifact shape."""
    return {
        "id": row["artifact_id"],
        "kind": row["kind"],
        "mime_type": row["mime_type"],
        "size_bytes": row["size_bytes"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "source_id": row["source_id"],
        "job_id": row["job_id"],
    }

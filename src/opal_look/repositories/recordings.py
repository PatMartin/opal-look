"""recordings table: explicit independent recordings (v1.5)."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol


class RecordingRepository(Protocol):
    def get(self, recording_id: str) -> sqlite3.Row | None: ...
    def list(self, limit: int, cursor: str | None) -> list[sqlite3.Row]: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, recording_id: str, fields: dict[str, Any]) -> None: ...
    def count_active(self) -> int: ...
    def list_active(self) -> list[sqlite3.Row]: ...
    def for_source(self, source_id: str) -> list[sqlite3.Row]: ...


class SqliteRecordingRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, recording_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM recordings WHERE recording_id = ?",
            (recording_id,)).fetchone()

    def list(self, limit=50, cursor=None):
        q = "SELECT * FROM recordings"
        params: list = []
        if cursor:
            q += " WHERE created_at < ? OR (created_at = ? AND recording_id < ?)"
            parts = cursor.split("|")
            params.extend([parts[0], parts[0], parts[1]])
        q += " ORDER BY created_at DESC, recording_id DESC LIMIT ?"
        params.append(limit + 1)
        return self._conn.execute(q, params).fetchall()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO recordings (recording_id, source_id, pipeline_id, "
            "include_audio, max_duration_seconds, output_json, state, "
            "media_id, failure, bytes_written, frames_written, created_at, "
            "started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fields["recording_id"], fields["source_id"],
             fields.get("pipeline_id"), fields.get("include_audio", 0),
             fields.get("max_duration_seconds"),
             fields.get("output_json", "null"), fields.get("state", "starting"),
             fields.get("media_id"), fields.get("failure"),
             fields.get("bytes_written", 0), fields.get("frames_written", 0),
             fields["created_at"], fields.get("started_at"),
             fields.get("finished_at")))

    def update(self, recording_id: str, fields: dict[str, Any]) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(
            f"UPDATE recordings SET {cols} WHERE recording_id = ?",
            (*fields.values(), recording_id))

    def count_active(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM recordings "
            "WHERE state IN ('starting','recording','stopping')"
        ).fetchone()["n"]

    def list_active(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM recordings WHERE state IN "
            "('starting','recording','stopping')").fetchall()

    def for_source(self, source_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM recordings WHERE source_id = ? "
            "AND state IN ('starting','recording','stopping')",
            (source_id,)).fetchall()

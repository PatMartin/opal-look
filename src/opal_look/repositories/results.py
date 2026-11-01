"""results table: persisted analysis metadata history."""

from __future__ import annotations

import sqlite3
from typing import Any, Protocol


class ResultRepository(Protocol):
    def get(self, result_id: str) -> sqlite3.Row | None: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def delete(self, result_id: str) -> None: ...
    def latest_for_session(self, session_id: str) -> sqlite3.Row | None: ...
    def page(
        self,
        now: str,
        bound: str | None,
        after: list | None,
        limit: int,
        filters: dict[str, Any],
    ) -> list[sqlite3.Row]: ...


class SqliteResultRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, result_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM results WHERE result_id = ?", (result_id,)
        ).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO results (result_id, session_id, source_id, media_id, model_id, "
            "engine_id, task, profile_id, frame_index, tracking_epoch, captured_at, "
            "analyzed_at, position_ms, width, height, duration_ms, stored, expires_at, "
            "payload, engine_metadata, settings) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fields["result_id"],
                fields.get("session_id"),
                fields.get("source_id"),
                fields.get("media_id"),
                fields["model_id"],
                fields["engine_id"],
                fields["task"],
                fields.get("profile_id"),
                fields["frame_index"],
                fields["tracking_epoch"],
                fields["captured_at"],
                fields["analyzed_at"],
                fields.get("position_ms"),
                fields["width"],
                fields["height"],
                fields["duration_ms"],
                fields.get("stored", 1),
                fields.get("expires_at"),
                fields["payload"],
                fields["engine_metadata"],
                fields["settings"],
            ),
        )

    def delete(self, result_id: str) -> None:
        self._conn.execute("DELETE FROM results WHERE result_id = ?", (result_id,))

    def latest_for_session(self, session_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM results WHERE session_id = ? "
            "ORDER BY frame_index DESC, analyzed_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()

    def page(
        self,
        now: str,
        bound: str | None,
        after: list | None,
        limit: int,
        filters: dict[str, Any],
    ) -> list[sqlite3.Row]:
        """Stored, unexpired results, newest-first (analyzed_at, result_id desc)."""
        query = "SELECT * FROM results WHERE stored = 1 AND expires_at > ?"
        params: list = [now]
        if bound is not None:
            query += " AND analyzed_at <= ?"
            params.append(bound)
        for key in ("session_id", "source_id", "model_id", "task"):
            if filters.get(key) is not None:
                query += f" AND {key} = ?"
                params.append(filters[key])
        if filters.get("from") is not None:
            query += " AND analyzed_at >= ?"
            params.append(filters["from"])
        if filters.get("to") is not None:
            query += " AND analyzed_at < ?"
            params.append(filters["to"])
        if filters.get("class_label") is not None:
            query += " AND payload LIKE ?"
            params.append(f'%"label": "{filters["class_label"]}"%')
        if filters.get("text") is not None:
            query += " AND task = 'ocr' AND payload LIKE ?"
            params.append(f"%{filters['text']}%")
        if after is not None:
            query += " AND (analyzed_at < ? OR (analyzed_at = ? AND result_id < ?))"
            params += [after[0], after[0], after[1]]
        query += " ORDER BY analyzed_at DESC, result_id DESC LIMIT ?"
        params.append(limit + 1)
        return self._conn.execute(query, params).fetchall()

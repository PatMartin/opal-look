"""sessions table: durable session records (runtime state, not config)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol

from ..timeutil import now_iso

TERMINAL_STATES = ("stopped", "completed", "failed")

IDEMPOTENCY_TTL_HOURS = 24


class SessionRepository(Protocol):
    def get(self, session_id: str) -> sqlite3.Row | None: ...
    def insert(self, fields: dict[str, Any]) -> None: ...
    def update(self, session_id: str, fields: dict[str, Any]) -> None: ...
    def delete(self, session_id: str) -> None: ...
    def count_nonterminal(self, kind: str | None = None, rid: str | None = None) -> int: ...
    def fail_interrupted(self, error_json: str) -> None: ...
    def page(self, now: str, retention_hours: int, filters: dict, after: list | None, limit: int) -> list[sqlite3.Row]: ...


class SqliteSessionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, session_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()

    def insert(self, fields: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO sessions (session_id, source_id, profile_id, model_id, engine_id, "
            "task, settings, reconnect, store_results, state, created_at, started_at, "
            "finished_at, start_position_ms, end_position_ms, frames_analyzed, "
            "frames_dropped, tracking_epoch, last_result_id, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, NULL, NULL)",
            (
                fields["session_id"], fields["source_id"], fields.get("profile_id"),
                fields["model_id"], fields["engine_id"], fields["task"],
                json.dumps(fields["settings"]),
                json.dumps(fields["reconnect"]) if fields.get("reconnect") else None,
                int(fields["store_results"]), fields["state"], fields["created_at"],
                fields.get("started_at"), fields.get("finished_at"),
                fields.get("start_position_ms"), fields.get("end_position_ms"),
            ),
        )

    def update(self, session_id: str, fields: dict[str, Any]) -> None:
        encoded = {
            k: (json.dumps(v) if k in ("settings", "reconnect", "error") else v)
            for k, v in fields.items()
        }
        assignments = ", ".join(f"{k} = ?" for k in encoded)
        self._conn.execute(
            f"UPDATE sessions SET {assignments} WHERE session_id = ?",
            (*encoded.values(), session_id),
        )

    def delete(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def count_nonterminal(self, kind: str | None = None, rid: str | None = None) -> int:
        query = "SELECT COUNT(*) AS n FROM sessions WHERE state NOT IN ('stopped','completed','failed')"
        params: list = []
        if kind is not None and rid is not None:
            if kind == "media":
                query += " AND source_id IN (SELECT source_id FROM sources WHERE locator = ?)"
                params.append(rid)
            else:
                col = {"engine": "engine_id", "model": "model_id", "source": "source_id",
                       "profile": "profile_id"}.get(kind)
                if col:
                    query += f" AND {col} = ?"
                    params.append(int(rid) if col == "profile_id" else rid)
        return self._conn.execute(query, params).fetchone()["n"]

    def get_idempotency(self, key: str, now: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM idempotency_keys WHERE key = ? AND expires_at > ?", (key, now)
        ).fetchone()

    def put_idempotency(self, key: str, fingerprint: str, session_id: str) -> None:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        self._conn.execute(
            "INSERT OR REPLACE INTO idempotency_keys (key, fingerprint, session_id, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (key, fingerprint, session_id,
             now.isoformat().replace("+00:00", "Z"),
             (now + timedelta(hours=IDEMPOTENCY_TTL_HOURS)).isoformat().replace("+00:00", "Z")),
        )

    def fail_interrupted(self, error_json: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET state = 'failed', finished_at = ?, error = ? "
            "WHERE state NOT IN ('stopped','completed','failed')",
            (now_iso(), error_json),
        )

    def page(self, now: str, retention_hours: int, filters: dict, after: list | None, limit: int) -> list[sqlite3.Row]:
        query = (
            "SELECT * FROM sessions WHERE (state NOT IN ('stopped','completed','failed') "
            "OR finished_at > datetime('now', ?))"
        )
        params: list = [f"-{retention_hours} hours"]
        if filters.get("source_id") is not None:
            query += " AND source_id = ?"
            params.append(filters["source_id"])
        if filters.get("state") is not None:
            query += " AND state = ?"
            params.append(filters["state"])
        if after is not None:
            query += " AND (created_at < ? OR (created_at = ? AND session_id < ?))"
            params += [after[0], after[0], after[1]]
        query += " ORDER BY created_at DESC, session_id DESC LIMIT ?"
        params.append(limit + 1)
        return self._conn.execute(query, params).fetchall()

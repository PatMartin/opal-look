"""observations table: opt-in retained v1.5 observations (immutable)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol


class ObservationRepository(Protocol):
    def insert(self, obs: dict[str, Any], expires_at: str | None) -> None: ...
    def get(self, observation_id: str) -> sqlite3.Row | None: ...
    def page(self, now: str, filters: dict,
             limit: int) -> list[sqlite3.Row]: ...


class SqliteObservationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, obs: dict[str, Any], expires_at: str | None) -> None:
        labels = sorted({it.get("label") for it in obs.get("items", [])
                         if it.get("label")})
        self._conn.execute(
            "INSERT INTO observations (observation_id, created_at, observed_at, "
            "source_id, media_id, monitor_id, job_id, session_id, pipeline_id, "
            "stage_id, task, labels, expires_at, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (obs["id"], obs["created_at"], obs["observed_at"],
             obs.get("source_id"), obs.get("media_id"), obs.get("monitor_id"),
             obs.get("job_id"), obs.get("session_id"), obs["pipeline_id"],
             obs.get("stage_id"),
             obs["task"], json.dumps(labels), expires_at, json.dumps(obs)),
        )

    def get(self, observation_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM observations WHERE observation_id = ?", (observation_id,)
        ).fetchone()

    def page(self, now: str, filters: dict,
             limit: int) -> list[sqlite3.Row]:
        query = "SELECT * FROM observations WHERE (expires_at IS NULL OR expires_at > ?)"
        params: list = [now]
        if filters.get("source_id") is not None:
            query += " AND source_id = ?"
            params.append(filters["source_id"])
        if filters.get("monitor_id") is not None:
            query += " AND monitor_id = ?"
            params.append(filters["monitor_id"])
        if filters.get("job_id") is not None:
            query += " AND job_id = ?"
            params.append(filters["job_id"])
        if filters.get("session_id") is not None:
            query += " AND session_id = ?"
            params.append(filters["session_id"])
        if filters.get("task") is not None:
            query += " AND task = ?"
            params.append(filters["task"])
        if filters.get("label") is not None:
            query += " AND labels LIKE ?"
            params.append(f"%{filters['label']}%")
        if filters.get("after") is not None:
            query += " AND observed_at >= ?"
            params.append(filters["after"])
        if filters.get("before") is not None:
            query += " AND observed_at <= ?"
            params.append(filters["before"])
        query += " ORDER BY created_at DESC, observation_id DESC LIMIT ?"
        params.append(limit)
        return self._conn.execute(query, params).fetchall()

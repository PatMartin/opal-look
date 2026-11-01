"""SQLite connection owner + unit of work.

Store owns the connection and schema; per-aggregate repositories
(src/opal_look/repositories/) provide persistence operations and are the
only supported data path. write_txn() is the unit-of-work context manager
used for atomic check-and-mutate (If-Match + write + revision bump).
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .repositories import (
    SqliteEngineRepository,
    SqliteMediaRepository,
    SqliteMetaRepository,
    SqliteModelRepository,
    SqliteProfileRepository,
    SqliteResultRepository,
    SqliteSessionRepository,
    SqliteSettingsRepository,
    SqliteSnapshotRepository,
    SqliteSourceRepository,
    new_revision,
)


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "opal-look.db"
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._write_lock = threading.Lock()
        self._init_schema()

        self.meta = SqliteMetaRepository(self._conn)
        self.settings = SqliteSettingsRepository(self._conn)
        self.engines = SqliteEngineRepository(self._conn)
        self.models = SqliteModelRepository(self._conn)
        self.sources = SqliteSourceRepository(self._conn)
        self.profiles = SqliteProfileRepository(self._conn)
        self.media = SqliteMediaRepository(self._conn)
        self.results = SqliteResultRepository(self._conn)
        self.snapshots = SqliteSnapshotRepository(self._conn)
        self.sessions = SqliteSessionRepository(self._conn)

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS setting_overrides (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS engines (
                engine_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                execution TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                config TEXT NOT NULL DEFAULT '{}',
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS models (
                model_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                engine_id TEXT NOT NULL,
                resource TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                locator TEXT NOT NULL,
                credential_ref TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                source_options TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                model_id TEXT NOT NULL,
                task TEXT NOT NULL,
                settings TEXT NOT NULL DEFAULT '{}',
                active INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS media (
                media_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                kind TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                path TEXT NOT NULL,
                width INTEGER,
                height INTEGER,
                duration_ms INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS results (
                result_id TEXT PRIMARY KEY,
                session_id TEXT,
                source_id TEXT,
                media_id TEXT,
                model_id TEXT NOT NULL,
                engine_id TEXT NOT NULL,
                task TEXT NOT NULL,
                profile_id INTEGER,
                frame_index INTEGER NOT NULL,
                tracking_epoch INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                position_ms INTEGER,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                duration_ms REAL NOT NULL,
                stored INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT,
                payload TEXT NOT NULL,
                engine_metadata TEXT NOT NULL DEFAULT '{}',
                settings TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                result_id TEXT NOT NULL,
                annotated INTEGER NOT NULL DEFAULT 0,
                path TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                profile_id INTEGER,
                model_id TEXT NOT NULL,
                engine_id TEXT NOT NULL,
                task TEXT NOT NULL,
                settings TEXT NOT NULL,
                reconnect TEXT,
                store_results INTEGER NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                start_position_ms INTEGER,
                end_position_ms INTEGER,
                frames_analyzed INTEGER NOT NULL DEFAULT 0,
                frames_dropped INTEGER NOT NULL DEFAULT 0,
                tracking_epoch INTEGER NOT NULL DEFAULT 0,
                last_result_id TEXT,
                error TEXT
            );
            """
        )
        if self._conn.execute(
            "SELECT value FROM meta WHERE key = 'config_revision'"
        ).fetchone() is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('config_revision', ?)",
                (new_revision(),),
            )

    def ping(self) -> bool:
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.Error:
            return False
        return True

    @contextmanager
    def write_txn(self) -> Iterator["Store"]:
        """Exclusive write transaction for atomic check-and-mutate."""
        with self._write_lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # Revision facade (cross-cutting; delegates to meta repository).
    def config_revision(self) -> str:
        return self.meta.revision()

    def bump_revision(self) -> str:
        """Advance the global configuration revision. Call inside write_txn."""
        return self.meta.bump_revision()

    def close(self) -> None:
        self._conn.close()

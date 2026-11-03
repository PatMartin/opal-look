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


class _LockedConnection:
    """Serializes statement execution across threads.

    A single sqlite3 connection is not safe for concurrent use even with
    check_same_thread=False (SQLITE_MISUSE under contention). Repositories
    and store helpers go through this proxy; write_txn() holds the same
    re-entrant lock for its whole transaction so statements issued inside
    it (same thread) pass through while other threads wait.
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._conn.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return self._conn.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._conn.executescript(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "opal-look.db"
        raw = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        self._txn_state = threading.local()
        self._conn = _LockedConnection(raw, self._lock)
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
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT '',
                tasks TEXT NOT NULL DEFAULT '[]',
                options TEXT NOT NULL DEFAULT '{}',
                resource_ref TEXT
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
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            """
        )
        self._migrate()
        if self._conn.execute(
            "SELECT value FROM meta WHERE key = 'config_revision'"
        ).fetchone() is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('config_revision', ?)",
                (new_revision(),),
            )

    def _migrate(self) -> None:
        """Idempotent column adds for pre-v1.5 databases."""
        import json as _json

        from .timeutil import now_iso

        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(models)")}
        for col, ddl in (
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
            ("tasks", "TEXT NOT NULL DEFAULT '[]'"),
            ("options", "TEXT NOT NULL DEFAULT '{}'"),
            ("resource_ref", "TEXT"),
        ):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE models ADD COLUMN {col} {ddl}")
        self._conn.execute("UPDATE models SET created_at = ? WHERE created_at = ''",
                           (now_iso(),))
        for row in self._conn.execute(
            "SELECT model_id, resource FROM models WHERE resource_ref IS NULL"
        ).fetchall():
            res = _json.loads(row["resource"])
            ref = res.get("ref") or res.get("path") or _json.dumps(res)
            self._conn.execute(
                "UPDATE models SET resource_ref = ? WHERE model_id = ?",
                (ref, row["model_id"]),
            )

    def ping(self) -> bool:
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.Error:
            return False
        return True

    @contextmanager
    def write_txn(self) -> Iterator["Store"]:
        """Exclusive write transaction for atomic check-and-mutate.

        Nestable: an inner write_txn on the same thread becomes a SAVEPOINT,
        so service helpers may open their own unit of work inside a
        handler-level transaction (e.g. an atomic check + multi-step import).
        An inner failure rolls back only to its savepoint; an outer failure
        rolls back everything. Transactions never nest across threads — the
        store lock serializes them.
        """
        with self._lock:
            depth = getattr(self._txn_state, "depth", 0)
            if depth == 0:
                self._txn_state.depth = 1
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    yield self
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                else:
                    self._conn.execute("COMMIT")
                finally:
                    self._txn_state.depth = 0
            else:
                savepoint = f"opal_sp_{depth}"
                self._txn_state.depth = depth + 1
                self._conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    yield self
                except BaseException:
                    self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                    raise
                else:
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                finally:
                    self._txn_state.depth = depth

    # Revision facade (cross-cutting; delegates to meta repository).
    def config_revision(self) -> str:
        return self.meta.revision()

    def bump_revision(self) -> str:
        """Advance the global configuration revision. Call inside write_txn."""
        return self.meta.bump_revision()

    def close(self) -> None:
        self._conn.close()


def sweep_expired(store: "Store") -> dict[str, int]:
    """Purge rows past their expires_at (media/results/snapshots/idempotency).
    Returns per-table delete counts. Call on startup and periodically."""
    from .timeutil import now_iso
    counts = {}
    now = now_iso()
    for table, col in (("media", "expires_at"), ("results", "expires_at"),
                       ("snapshots", "expires_at"), ("idempotency_keys", "expires_at")):
        cur = store._conn.execute(
            f"DELETE FROM {table} WHERE {col} IS NOT NULL AND {col} <= ?", (now,))
        counts[table] = cur.rowcount
    store._conn.execute(
        "DELETE FROM sessions WHERE state IN ('stopped','completed','failed') "
        "AND finished_at < datetime('now', '-30 days')")
    return counts

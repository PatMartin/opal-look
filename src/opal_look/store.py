"""SQLite connection owner + unit of work.

Store owns the connection and schema; per-aggregate repositories
(src/opal_look/repositories/) provide persistence operations and are the
only supported data path. write_txn() is the unit-of-work context manager
used for atomic check-and-mutate (If-Match + write + revision bump).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .repositories import (
    SqliteEngineRepository,
    SqliteMetaRepository,
    SqliteProfileRepository,
    SqlitePersonaRepository,
    SqliteSettingsRepository,
    new_revision,
)
from .timeutil import now_iso

# Tables retired by the MVP contract replacement (v1.7.1 clean cut).
_RETIRED_TABLES = (
    "models", "sources", "observations", "recordings", "jobs", "monitors",
    "pipelines", "artifacts", "rules", "zones", "media", "results",
    "snapshots", "sessions",
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
        self.profiles = SqliteProfileRepository(self._conn)
        self.personas = SqlitePersonaRepository(self._conn)

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
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                active INTEGER NOT NULL DEFAULT 0,
                shared TEXT NOT NULL DEFAULT '{}',
                modules TEXT NOT NULL DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS personas (
                persona_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                voice_id TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                origin TEXT NOT NULL DEFAULT 'local',
                created_at TEXT,
                updated_at TEXT
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
        """Drop retired tables and apply idempotent column adds."""
        for table in _RETIRED_TABLES:
            self._conn.execute(f"DROP TABLE IF EXISTS {table}")
        ocols = {r["name"] for r in self._conn.execute(
            "PRAGMA table_info(setting_overrides)")}
        if "updated_at" not in ocols:
            self._conn.execute(
                "ALTER TABLE setting_overrides ADD COLUMN updated_at TEXT")
        pcols = {r["name"] for r in self._conn.execute(
            "PRAGMA table_info(profiles)")}
        if "model_id" in pcols or "shared" not in pcols:
            self._migrate_profiles_to_namespaced(pcols)
        self._migrate_personas_if_needed()

    def _migrate_profiles_to_namespaced(self, pcols: set) -> None:
        """Rebuild a v1.7-era profiles table into portable documents.

        `shared` starts empty and every legacy service-defined field moves
        under `modules["opal-look-legacy"]` - an unrecognized compartment
        the kernel preserves verbatim through reads and config save/load.
        Existing integer ids become their string form ("3" stays
        addressable as profile_id "3").
        """
        rows = self._conn.execute("SELECT * FROM profiles").fetchall()
        self._conn.execute(
            """
            CREATE TABLE profiles_v2 (
                profile_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                active INTEGER NOT NULL DEFAULT 0,
                shared TEXT NOT NULL DEFAULT '{}',
                modules TEXT NOT NULL DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        for row in rows:
            data = {}
            if "data" in pcols and row["data"]:
                try:
                    data = json.loads(row["data"])
                except (TypeError, json.JSONDecodeError):
                    data = {}
            legacy = {
                k: v for k, v in data.items()
                if k not in ("created_at", "updated_at")
            }
            for col in ("model_id", "task"):
                if col in pcols and row[col]:
                    legacy.setdefault(col, row[col])
            if "settings" in pcols and row["settings"] not in (None, "", "{}"):
                try:
                    legacy.setdefault("settings", json.loads(row["settings"]))
                except (TypeError, json.JSONDecodeError):
                    pass
            modules = {"opal-look-legacy": legacy} if legacy else {}
            created = data.get("created_at") or now_iso()
            self._conn.execute(
                "INSERT INTO profiles_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(row["profile_id"]), row["name"], None,
                 int(row["active"]), "{}", json.dumps(modules),
                 created, data.get("updated_at") or created),
            )
        self._conn.execute("DROP TABLE profiles")
        self._conn.execute("ALTER TABLE profiles_v2 RENAME TO profiles")

    def _migrate_personas_if_needed(self) -> None:
        """Rebuild a pre-0.1.0 personas table (different column set) into the
        current schema, preserving rows; absent or conforming tables are
        left alone."""
        cols = {r["name"] for r in self._conn.execute(
            "PRAGMA table_info(personas)")}
        if not cols or "origin" in cols:
            return
        rows = self._conn.execute("SELECT * FROM personas").fetchall()
        self._conn.execute("ALTER TABLE personas RENAME TO personas_old")
        self._conn.execute(
            """
            CREATE TABLE personas (
                persona_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                voice_id TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                origin TEXT NOT NULL DEFAULT 'local',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        for row in rows:
            keys = row.keys()
            def col(name, default=None):
                return row[name] if name in keys else default
            now = now_iso()
            self._conn.execute(
                "INSERT OR IGNORE INTO personas VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(col("persona_id") or col("id")),
                 col("name") or str(col("persona_id") or col("id")),
                 col("description"), col("voice_id"),
                 int(col("enabled", col("active", 1))), "local",
                 col("created_at") or now,
                 col("updated_at") or col("created_at") or now),
            )
        self._conn.execute("DROP TABLE personas_old")

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
    """Purge expired idempotency keys. Returns per-table delete counts."""
    from .timeutil import now_iso
    cur = store._conn.execute(
        "DELETE FROM idempotency_keys WHERE expires_at IS NOT NULL "
        "AND expires_at <= ?", (now_iso(),))
    return {"idempotency_keys": cur.rowcount}

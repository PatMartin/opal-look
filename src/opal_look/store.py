"""SQLite-backed durable store. Schema grows with each implementation step."""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


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
            """
        )
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'config_revision'").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('config_revision', ?)",
                (_new_revision(),),
            )

    def ping(self) -> bool:
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.Error:
            return False
        return True

    @contextmanager
    def write_txn(self) -> Iterator[None]:
        """Exclusive write transaction for atomic check-and-mutate."""
        with self._write_lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def config_revision(self) -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'config_revision'").fetchone()
        return row["value"]

    def bump_revision(self) -> str:
        """Advance the global configuration revision. Call inside write_txn."""
        revision = _new_revision()
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES ('config_revision', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (revision,),
        )
        return revision

    def setting_overrides(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT key, value FROM setting_overrides").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def set_setting(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO setting_overrides (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def delete_setting(self, key: str) -> None:
        self._conn.execute("DELETE FROM setting_overrides WHERE key = ?", (key,))

    # -- engines -----------------------------------------------------------

    def list_engines(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM engines ORDER BY rowid").fetchall()

    def get_engine(self, engine_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM engines WHERE engine_id = ?", (engine_id,)
        ).fetchone()

    def update_engine(self, engine_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [json.dumps(v) if isinstance(v, dict) else int(v) if isinstance(v, bool) else v for v in fields.values()]
        self._conn.execute(
            f"UPDATE engines SET {assignments} WHERE engine_id = ?", (*values, engine_id)
        )

    # -- models ------------------------------------------------------------

    def list_models(
        self, engine_id: str | None = None, enabled: bool | None = None
    ) -> list[sqlite3.Row]:
        query = "SELECT * FROM models"
        clauses, params = [], []
        if engine_id is not None:
            clauses.append("engine_id = ?")
            params.append(engine_id)
        if enabled is not None:
            clauses.append("enabled = ?")
            params.append(int(enabled))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        return self._conn.execute(query + " ORDER BY rowid", params).fetchall()

    def get_model(self, model_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM models WHERE model_id = ?", (model_id,)
        ).fetchone()

    def insert_model(
        self, model_id: str, name: str, engine_id: str, resource: dict, enabled: bool
    ) -> None:
        self._conn.execute(
            "INSERT INTO models (model_id, name, engine_id, resource, enabled) VALUES (?, ?, ?, ?, ?)",
            (model_id, name, engine_id, json.dumps(resource), int(enabled)),
        )

    def update_model(self, model_id: str, fields: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [json.dumps(v) if isinstance(v, dict) else int(v) if isinstance(v, bool) else v for v in fields.values()]
        self._conn.execute(
            f"UPDATE models SET {assignments} WHERE model_id = ?", (*values, model_id)
        )

    def delete_model(self, model_id: str) -> None:
        self._conn.execute("DELETE FROM models WHERE model_id = ?", (model_id,))

    def close(self) -> None:
        self._conn.close()


def _new_revision() -> str:
    """Opaque strong entity-tag for the logical configuration."""
    return '"' + secrets.token_hex(16) + '"'

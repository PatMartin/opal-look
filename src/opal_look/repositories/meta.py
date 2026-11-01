"""meta table: global configuration revision and misc key/value."""

from __future__ import annotations

import secrets
import sqlite3
from typing import Protocol


class MetaRepository(Protocol):
    def revision(self) -> str: ...
    def bump_revision(self) -> str: ...
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


def new_revision() -> str:
    """Opaque strong entity-tag for the logical configuration."""
    return '"' + secrets.token_hex(16) + '"'


class SqliteMetaRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def revision(self) -> str:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'config_revision'"
        ).fetchone()
        return row["value"]

    def bump_revision(self) -> str:
        """Advance the global configuration revision. Call inside write_txn."""
        revision = new_revision()
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES ('config_revision', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (revision,),
        )
        return revision

    def get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

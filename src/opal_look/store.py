"""SQLite-backed durable store. Schema grows with each implementation step."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "opal-look.db"
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._conn.commit()

    def ping(self) -> bool:
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.Error:
            return False
        return True

    def close(self) -> None:
        self._conn.close()

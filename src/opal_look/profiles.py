"""Profile read shape (kernel OpalProfile)."""

from __future__ import annotations

import json
import sqlite3


def profile_read(row: sqlite3.Row) -> dict[str, Any]:
    """Kernel OpalProfile: opaque fields persisted verbatim in `data`."""
    data = json.loads(row["data"] or "{}") if "data" in row.keys() else {}
    return {
        "id": row["profile_id"],
        "name": row["name"],
        "is_active": bool(row["active"]),
        **data,
    }

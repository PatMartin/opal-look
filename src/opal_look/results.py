"""Result row -> AnalysisResult assembly."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def result_read(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "result_id": row["result_id"],
        "session_id": row["session_id"],
        "source_id": row["source_id"],
        "media_id": row["media_id"],
        "model_id": row["model_id"],
        "engine_id": row["engine_id"],
        "task": row["task"],
        "frame_index": row["frame_index"],
        "tracking_epoch": row["tracking_epoch"],
        "captured_at": row["captured_at"],
        "analyzed_at": row["analyzed_at"],
        "position_ms": row["position_ms"],
        "width": row["width"],
        "height": row["height"],
        "duration_ms": row["duration_ms"],
        "stored": bool(row["stored"]),
        "expires_at": row["expires_at"],
        "payload": json.loads(row["payload"]),
        "engine_metadata": json.loads(row["engine_metadata"]),
    }

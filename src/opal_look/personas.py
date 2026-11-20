"""Persona read shape (kernel OpalPersonaRead) + record validation."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from .errors import ApiError

PERSONA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def check_persona_id(persona_id: Any) -> None:
    if (not isinstance(persona_id, str)
            or not PERSONA_ID_RE.match(persona_id)
            or len(persona_id) > 200):
        raise ApiError(
            422, "persona_id must match ^[A-Za-z0-9][A-Za-z0-9._-]*$ "
                 "and be 1-200 chars.")


def check_persona_fields(body: dict, *, partial: bool) -> None:
    if "name" in body:
        name = body["name"]
        if not isinstance(name, str) or not name or len(name) > 200:
            raise ApiError(422, "name must be a string of 1-200 chars.")
    if "description" in body and body["description"] is not None:
        if not isinstance(body["description"], str) \
                or len(body["description"]) > 1000:
            raise ApiError(
                422, "description must be a string up to 1000 chars or null.")
    if "voice_id" in body and body["voice_id"] is not None:
        if not isinstance(body["voice_id"], str) or not body["voice_id"]:
            raise ApiError(422, "voice_id must be a non-empty string or null.")
    if "enabled" in body and not isinstance(body["enabled"], bool):
        raise ApiError(422, "enabled must be a boolean.")


def persona_read(row: sqlite3.Row) -> dict:
    return {
        "persona_id": row["persona_id"],
        "name": row["name"],
        "description": row["description"],
        "voice_id": row["voice_id"],
        "enabled": bool(row["enabled"]),
        "origin": row["origin"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

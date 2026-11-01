"""Opaque cursor pagination helpers.

Cursor = base64url JSON {v, f, k, t}: version, bound filter hash,
last-key tuple, issued-at epoch. Filter mismatch or malformed -> 422;
explicitly expired -> 410.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

from .errors import ApiError

CURSOR_TTL_SECONDS = 600


def filter_key(filters: dict[str, Any]) -> str:
    canonical = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def encode_cursor(fkey: str, last_key: list) -> str:
    payload = {"v": 1, "f": fkey, "k": last_key, "t": int(time.time())}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(raw: str | None, fkey: str) -> list | None:
    if raw is None:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except Exception:
        raise ApiError(422, "Invalid cursor.")
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ApiError(422, "Invalid cursor.")
    if payload.get("f") != fkey:
        raise ApiError(422, "Cursor does not match the requested filter set.")
    if int(time.time()) - int(payload.get("t", 0)) > CURSOR_TTL_SECONDS:
        raise ApiError(410, "Cursor has expired.", code="gone")
    key = payload.get("k")
    if not isinstance(key, list):
        raise ApiError(422, "Invalid cursor.")
    return key

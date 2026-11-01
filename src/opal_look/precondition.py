"""Strong-ETag / If-Match precondition handling for logical configuration.

Every configuration mutation must be checked atomically against the single
global revision inside a Store.write_txn: missing -> 428, stale -> 412,
malformed -> 422. '*' is the explicit unconditional escape hatch.
"""

from __future__ import annotations

from fastapi import Request

from .errors import ApiError
from .store import Store


def check_if_match(request: Request, store: Store) -> None:
    raw = request.headers.get("if-match")
    if raw is None:
        raise ApiError(
            428,
            "If-Match header is required for configuration mutations.",
            code="precondition_required",
        )
    raw = raw.strip()
    if raw == "*":
        return
    if (
        "," in raw
        or raw[:2].lower() == "w/"
        or len(raw) < 2
        or not (raw.startswith('"') and raw.endswith('"'))
    ):
        raise ApiError(
            422,
            "Malformed If-Match: expected a single strong entity-tag or '*'.",
            code="invalid_request",
        )
    if raw != store.config_revision():
        raise ApiError(
            412,
            "If-Match does not match the current configuration revision.",
            code="precondition_failed",
        )

"""Idempotency-Key admission header for replay-safe submissions.

Per contract: optional header of 1..128 characters; a matching replay returns
the original admission, a different payload with the same key returns 409,
and the reservation lives 24 hours. Format validation is shared here so all
admission endpoints (sessions today; jobs/recordings later) enforce the same
bounds.
"""

from __future__ import annotations

from fastapi import Request

from .errors import ApiError

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
MAX_KEY_LENGTH = 128


def request_idempotency_key(request: Request) -> str | None:
    """Return the validated Idempotency-Key or None when absent.

    Present-but-invalid (empty or >128 chars) -> 422.
    """
    raw = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if raw is None:
        return None
    if not 1 <= len(raw) <= MAX_KEY_LENGTH:
        raise ApiError(
            422,
            "Invalid Idempotency-Key header: expected 1-128 characters.",
        )
    return raw

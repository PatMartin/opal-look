"""Strong-ETag / If-Match precondition handling for logical configuration.

Two-phase contract enforcement:

* ``require_if_match`` — cheap presence/syntax validation a handler may run
  early: missing header -> 428, malformed value -> 422.
* ``check_if_match`` — the authoritative staleness check, run inside
  ``Store.write_txn`` so the comparison and the mutation + revision bump are
  atomic: stale -> 412. It re-validates presence/syntax, so calling it alone
  (inside the transaction) is also correct.

'*' is the explicit unconditional escape hatch. Runtime activity (sessions,
results, media, jobs) does not use If-Match and must not bump the revision.
"""

from __future__ import annotations

from fastapi import Request

from .errors import ApiError
from .store import Store


def require_if_match(request: Request) -> str:
    """Validate If-Match presence and syntax. Returns the stripped value.

    Missing -> 428 (precondition_required); anything other than a single
    strong entity-tag or '*' -> 422 (invalid_request). Staleness is not
    evaluated here; use check_if_match inside the write transaction.
    """
    raw = request.headers.get("if-match")
    if raw is None:
        raise ApiError(
            428,
            "If-Match header is required for configuration mutations.",
            code="precondition_required",
        )
    raw = raw.strip()
    if raw == "*":
        return raw
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
    return raw


def check_if_match(request: Request, store: Store) -> None:
    """Atomic If-Match verification. Call inside Store.write_txn."""
    raw = require_if_match(request)
    if raw == "*":
        return
    if raw != store.config_revision():
        raise ApiError(
            412,
            "If-Match does not match the current configuration revision.",
            code="precondition_failed",
        )

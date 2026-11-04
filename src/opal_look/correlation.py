"""X-Opal-* correlation header handling per OPAL suite standard v1.2.

Inbound tokens are opaque 1..128-char printable ASCII with no
control/whitespace characters; invalid client-supplied values yield 422.
Missing transaction/request IDs are generated; session/causation IDs are
propagated only when supplied. All known IDs are echoed on every response,
including errors, binary bodies and streams.

Unhandled exceptions are converted here to the OpalError envelope so the
500 response still carries the correct request/transaction IDs and X-Opal-*
headers (the framework's error middleware sits outside this layer and
would lose them). X-Opal-Session-Id is the caller's logical context only;
internal worker/session identities are never emitted in these headers.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("opal_look.correlation")

SESSION_ID_HEADER = "X-Opal-Session-Id"
TRANSACTION_ID_HEADER = "X-Opal-Transaction-Id"
REQUEST_ID_HEADER = "X-Opal-Request-Id"
CAUSATION_ID_HEADER = "X-Opal-Causation-Id"

CORRELATION_HEADERS = (
    SESSION_ID_HEADER,
    TRANSACTION_ID_HEADER,
    REQUEST_ID_HEADER,
    CAUSATION_ID_HEADER,
)

_TOKEN = re.compile(r"^[\x21-\x7e]{1,128}$")


@dataclass(frozen=True)
class CorrelationIds:
    session_id: str | None
    transaction_id: str
    request_id: str
    causation_id: str | None


_current: ContextVar[CorrelationIds | None] = ContextVar("opal_correlation", default=None)


def current_ids() -> CorrelationIds:
    """IDs for the in-flight request, or fresh ones outside a request."""
    ids = _current.get()
    if ids is None:
        return CorrelationIds(None, uuid.uuid4().hex, uuid.uuid4().hex, None)
    return ids


def envelope(
    ids: CorrelationIds,
    *,
    code: str,
    message: str,
    details: Any = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    """Build the OpalError body: error.{code,message,request_id,transaction_id,...}.

    ``details`` must be a JSON object per the contract schema; bare lists or
    scalars are wrapped as ``{"errors": [...]}`` so callers stay conformant.
    ``retryable`` is emitted only when explicitly set.
    """
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": ids.request_id,
        "transaction_id": ids.transaction_id,
        "session_id": ids.session_id,
        "causation_id": ids.causation_id,
    }
    if retryable is not None:
        error["retryable"] = bool(retryable)
    if details is not None:
        if isinstance(details, dict):
            error["details"] = details
        else:
            error["details"] = {
                "errors": details if isinstance(details, list) else [details]
            }
    return {"error": error}


def _new_id() -> str:
    return uuid.uuid4().hex


def _invalid_header_response(header_names: list[str]) -> JSONResponse:
    request_id = _new_id()
    transaction_id = _new_id()
    ids = CorrelationIds(None, transaction_id, request_id, None)
    return JSONResponse(
        status_code=422,
        content=envelope(
            ids,
            code="invalid_correlation_header",
            message="Invalid X-Opal-* header value: expected 1-128 printable "
            "ASCII characters without whitespace.",
            details={"headers": header_names},
        ),
        headers={TRANSACTION_ID_HEADER: transaction_id, REQUEST_ID_HEADER: request_id},
    )


def _unhandled_error_response(ids: CorrelationIds) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=envelope(
            ids,
            code="operation_failed",
            message="Unexpected internal error.",
        ),
    )


class CorrelationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        supplied = {name: request.headers.get(name) for name in CORRELATION_HEADERS}
        invalid = [name for name, value in supplied.items() if value is not None and not _TOKEN.match(value)]
        if invalid:
            return _invalid_header_response(invalid)

        ids = CorrelationIds(
            session_id=supplied[SESSION_ID_HEADER],
            transaction_id=supplied[TRANSACTION_ID_HEADER] or _new_id(),
            request_id=supplied[REQUEST_ID_HEADER] or _new_id(),
            causation_id=supplied[CAUSATION_ID_HEADER],
        )
        request.state.correlation = ids
        token = _current.set(ids)
        try:
            response = await call_next(request)
        except Exception:
            # The framework-level error handler runs outside this middleware
            # and would emit an envelope with fresh IDs and no X-Opal headers.
            logger.exception(
                "unhandled error during %s %s", request.method, request.url.path
            )
            response = _unhandled_error_response(ids)
        finally:
            _current.reset(token)

        response.headers[TRANSACTION_ID_HEADER] = ids.transaction_id
        response.headers[REQUEST_ID_HEADER] = ids.request_id
        if ids.session_id is not None:
            response.headers[SESSION_ID_HEADER] = ids.session_id
        if ids.causation_id is not None:
            response.headers[CAUSATION_ID_HEADER] = ids.causation_id
        return response

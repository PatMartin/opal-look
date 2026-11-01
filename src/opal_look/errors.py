"""OpalError envelope and exception-to-status mapping.

Every error response uses the suite OpalError shape:
error.{code,message,request_id,transaction_id,session_id,causation_id,details?}.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .correlation import CorrelationIds, current_ids

_STATUS_CODES = {
    400: "invalid_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    412: "precondition_failed",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "invalid_request",
    428: "precondition_required",
    429: "capacity_exceeded",
    500: "operation_failed",
    503: "service_unavailable",
    504: "analysis_timeout",
}


def default_code(status_code: int) -> str:
    return _STATUS_CODES.get(status_code, "operation_failed")


def envelope(
    ids: CorrelationIds,
    *,
    code: str,
    message: str,
    details: Any = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": ids.request_id,
        "transaction_id": ids.transaction_id,
        "session_id": ids.session_id,
        "causation_id": ids.causation_id,
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


class ApiError(Exception):
    """Domain error rendered as an OpalError response."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        code: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code or default_code(status_code)
        self.message = message
        self.details = details
        self.headers = headers


def _ids_for(request: Request) -> CorrelationIds:
    ids = getattr(request.state, "correlation", None)
    return ids if ids is not None else current_ids()


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(_ids_for(request), code=exc.code, message=exc.message, details=exc.details),
        headers=exc.headers,
    )


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(_ids_for(request), code=default_code(exc.status_code), message=message),
        headers=getattr(exc, "headers", None),
    )


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"loc": [str(part) for part in e.get("loc", ())], "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=envelope(
            _ids_for(request),
            code="invalid_request",
            message="Request validation failed.",
            details=details,
        ),
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=envelope(
            _ids_for(request),
            code="operation_failed",
            message="Unexpected internal error.",
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)

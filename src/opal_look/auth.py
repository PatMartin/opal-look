"""Opaque BearerAuth boundary for /api/v1 (v1.5 security requirement).

The contract applies BearerAuth (http bearer, opaque) to every operation.
A deployment configures the shared token out of band via OPAL_LOOK_TOKEN:

* token configured  -> every /api/v1 request must present
  ``Authorization: Bearer <token>``; missing/malformed/invalid -> 401
  (``unauthorized``) with ``WWW-Authenticate: Bearer`` and the OpalError
  envelope. Correlation middleware wraps this layer, so 401s still carry
  X-Opal-* headers.
* no token          -> local development mode; /api/v1 is unauthenticated.
  Binding a non-loopback interface in this mode is refused at startup
  (``assert_bind_allowed``) — non-loopback deployments require bearer auth.

The token is only ever read from the environment/config at startup: it is
never logged, exported, accepted in query strings, or echoed in responses.
403 (``forbidden``) remains for future scoped denials; a wellformed but
incorrect token is *invalid credentials* -> 401, not 403.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .correlation import current_ids, envelope

TOKEN_ENV = "OPAL_LOOK_TOKEN"
API_PREFIX = "/api/v1/"
_WWW_AUTHENTICATE = "Bearer"


def env_token() -> str | None:
    """Configured bearer token from the environment, or None.

    An explicitly empty/blank value is a misconfiguration, not an opt-out.
    """
    raw = os.environ.get(TOKEN_ENV)
    if raw is None:
        return None
    token = raw.strip()
    if not token:
        raise ValueError(f"{TOKEN_ENV} is set but empty")
    return token


def is_loopback_host(host: str) -> bool:
    host = (host or "").strip().lower().strip("[]")
    return host in ("localhost", "::1", "ip6-localhost") or host.startswith("127.")


def assert_bind_allowed(host: str, token: str | None) -> None:
    """Refuse to expose an unauthenticated API on a non-loopback interface."""
    if token is None and not is_loopback_host(host):
        raise SystemExit(
            f"Refusing to bind non-loopback host {host!r} without bearer auth; "
            f"set {TOKEN_ENV} or bind a loopback address."
        )


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """401 gate for /api/v1 requests when a token is configured."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        configured = request.app.state.auth_token
        if configured is None or not request.url.path.startswith(API_PREFIX):
            return await call_next(request)

        supplied = request.headers.get("authorization")
        if supplied is None:
            return _unauthorized(request, "Missing bearer credentials.")
        scheme, _, credential = supplied.partition(" ")
        if scheme.lower() != "bearer" or not credential.strip():
            return _unauthorized(request, "Malformed Authorization header.")
        if not hmac.compare_digest(credential.strip().encode(), configured.encode()):
            return _unauthorized(request, "Invalid bearer credentials.")
        return await call_next(request)


def _unauthorized(request: Request, message: str) -> JSONResponse:
    ids = getattr(request.state, "correlation", None) or current_ids()
    return JSONResponse(
        status_code=401,
        content=envelope(ids, code="unauthorized", message=message),
        headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
    )

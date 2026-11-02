"""Capture-adapter seam for live/finite video sources.

Mirrors the engine adapter pattern: adapters are registered per source
type in CAPTURE_REGISTRY (plugins via the 'opal_look.capture' entry-point
group). An adapter answers "is a capture backend installed" without
touching the network (installed/probe-read), performs a bounded live
connectivity probe for /validate (probe_stream), and produces frames for
sessions (open_stream) and single-frame analyze (grab).

Credentials are provisioned out of band: credential_ref names an
environment variable OPAL_LOOK_CRED_<REF> holding "user:pass". The
credential is injected into the locator only at connect time and is never
stored, logged, or returned by the API.
"""

from __future__ import annotations

import os
import queue
import re
import threading
from typing import Any, Protocol
from urllib.parse import quote, urlsplit, urlunsplit


class CaptureError(Exception):
    """Capture backend failed to open/read a stream (-> 503 / session failed)."""


class StreamError(CaptureError):
    """Established stream failed mid-read."""


class StreamEnded(CaptureError):
    """Stream ended. For live sources this means discontinuity (reconnect)."""


class CredentialUnavailable(CaptureError):
    """credential_ref is configured but the environment variable is missing."""


class FrameStream(Protocol):
    """Blocking frame source opened by a capture adapter."""

    def read(self) -> Any:  # PIL.Image
        """Return the next frame; raises StreamError/StreamEnded."""
        ...

    def close(self) -> None: ...


class CaptureAdapter(Protocol):
    source_type: str

    def installed(self) -> tuple[bool, str | None]:
        """(backend usable, message). No network/device access."""
        ...

    def probe_stream(
        self, locator: str, options: dict[str, Any], credentialed_locator: str
    ) -> dict[str, Any]:
        """Bounded live connectivity probe -> probe-result dict."""
        ...

    def open_stream(
        self, locator: str, options: dict[str, Any], credentialed_locator: str
    ) -> FrameStream:
        """Open a frame stream; raises CaptureError."""
        ...

    def grab(
        self, locator: str, options: dict[str, Any], credentialed_locator: str
    ) -> Any:
        """Open, read one frame, close -> PIL.Image; raises CaptureError."""
        ...


class CaptureRegistry:
    """Registry of installed capture adapters, keyed by source type."""

    def __init__(self) -> None:
        self._adapters: dict[str, CaptureAdapter] = {}

    def register(self, adapter: CaptureAdapter) -> None:
        self._adapters[adapter.source_type] = adapter

    def for_type(self, source_type: str) -> CaptureAdapter | None:
        return self._adapters.get(source_type)

    def all(self) -> list[CaptureAdapter]:
        return list(self._adapters.values())


CAPTURE_REGISTRY = CaptureRegistry()

try:
    from .capture_rtsp import RtspAvAdapter

    CAPTURE_REGISTRY.register(RtspAvAdapter())
except Exception:  # pragma: no cover - adapter import failure degrades gracefully
    pass


def capture_adapter_for(source_type: str) -> CaptureAdapter | None:
    return CAPTURE_REGISTRY.for_type(source_type)


def load_capture_plugins(registry: CaptureRegistry = CAPTURE_REGISTRY) -> None:
    """Optional plugin hook: register adapters from 'opal_look.capture' entry points."""
    import logging
    from importlib.metadata import entry_points

    for ep in entry_points(group="opal_look.capture"):
        try:
            registry.register(ep.load()())
        except Exception:
            logging.getLogger(__name__).warning("failed to load capture plugin %s", ep.name)


# -- credentials -------------------------------------------------------------

_CRED_ENV_RE = re.compile(r"[^A-Z0-9]+")


def credential_env_name(credential_ref: str) -> str:
    return "OPAL_LOOK_CRED_" + _CRED_ENV_RE.sub("_", credential_ref.upper())


def resolve_credentials(credential_ref: str | None) -> tuple[str, str] | None:
    """Return (user, password) for a credential_ref, or None when unset.

    Raises CredentialUnavailable when a ref is configured but the
    provisioned environment variable is absent or malformed.
    """
    if not credential_ref:
        return None
    raw = os.environ.get(credential_env_name(credential_ref))
    if raw is None:
        raise CredentialUnavailable(
            f"credential_ref {credential_ref!r} is not provisioned "
            f"(expected {credential_env_name(credential_ref)})"
        )
    user, sep, password = raw.partition(":")
    if not sep:
        raise CredentialUnavailable(
            f"credential {credential_env_name(credential_ref)} must be 'user:pass'"
        )
    return user, password


def credentialed_locator(locator: str, credential_ref: str | None) -> str:
    """Locator with URL-encoded userinfo injected; the ref itself never leaks."""
    creds = resolve_credentials(credential_ref)
    if creds is None:
        return locator
    user, password = creds
    parts = urlsplit(locator)
    host = parts.hostname or ""
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    authority = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}"
    if parts.port:
        authority += f":{parts.port}"
    return urlunsplit((parts.scheme, authority, parts.path, parts.query, parts.fragment))


# -- live frame pump ---------------------------------------------------------


class LiveFramePump:
    """Daemon thread draining a blocking FrameStream into a size-1 queue.

    Drop-oldest semantics keep live sessions on fresh frames; ``dropped``
    counts frames evicted unread and feeds frames_dropped. Terminal
    errors are delivered through get() as exceptions.
    """

    _SENTINEL = object()

    def __init__(self, stream: FrameStream, capacity: int = 1) -> None:
        self._stream = stream
        self._queue: queue.Queue = queue.Queue(maxsize=capacity)
        self.dropped = 0
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "LiveFramePump":
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            while not self._closed:
                frame = self._stream.read()
                try:
                    self._queue.put_nowait(frame)
                except queue.Full:
                    self._queue.get_nowait()
                    self.dropped += 1
                    self._queue.put_nowait(frame)
        except Exception as exc:  # delivered to consumer
            try:
                self._queue.put_nowait((self._SENTINEL, exc))
            except queue.Full:
                self._queue.get_nowait()
                self.dropped += 1
                self._queue.put_nowait((self._SENTINEL, exc))

    def get(self, timeout: float | None = None) -> Any:
        """Return the latest frame; raises the stream's terminal error."""
        item = self._queue.get(timeout=timeout)
        if isinstance(item, tuple) and item and item[0] is self._SENTINEL:
            raise item[1]
        return item

    def close(self) -> None:
        self._closed = True
        try:
            self._stream.close()
        except Exception:
            pass

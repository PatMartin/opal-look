"""RTSP capture adapter backed by PyAV (FFmpeg bindings).

source_options keys: ``transport`` (tcp|udp) -> ffmpeg rtsp_transport;
``timeout_ms`` -> stimeout/timeout in microseconds (default 5000).
PyAV is imported lazily so a missing/broken install degrades the adapter
to "not installed" rather than breaking the service.
"""

from __future__ import annotations

from typing import Any

from .capture import CaptureError, StreamEnded, StreamError

DEFAULT_TIMEOUT_MS = 5000

TRANSPORTS = {"tcp", "udp"}


def _import_av():
    try:
        import av

        return av
    except ImportError:
        return None


def _av_options(options: dict[str, Any]) -> dict[str, str]:
    timeout_us = str(int(options.get("timeout_ms") or DEFAULT_TIMEOUT_MS) * 1000)
    opts = {"stimeout": timeout_us, "timeout": timeout_us}
    transport = options.get("transport")
    if transport:
        opts["rtsp_transport"] = str(transport)
    return opts


def _probe(available: bool, message: str | None) -> dict[str, Any]:
    return {
        "available": available,
        "message": message,
        "width": None,
        "height": None,
        "fps": None,
        "duration_ms": None,
    }


class _AvFrameStream:
    def __init__(self, container: Any) -> None:
        self._container = container
        self._frames = container.decode(video=0)
        self._closed = False

    def read(self) -> Any:
        if self._closed:
            raise StreamEnded("stream closed")
        try:
            frame = next(self._frames)
        except StopIteration:
            raise StreamEnded("stream ended")
        except Exception as exc:
            raise StreamError(f"stream read failed: {exc}") from exc
        try:
            return frame.to_image()
        except Exception as exc:
            raise StreamError(f"frame decode failed: {exc}") from exc

    def close(self) -> None:
        self._closed = True
        try:
            self._container.close()
        except Exception:
            pass


class RtspAvAdapter:
    source_type = "rtsp"

    def installed(self) -> tuple[bool, str | None]:
        if _import_av() is None:
            return False, "PyAV (av) is not installed"
        return True, None

    def _open(self, options: dict[str, Any], credentialed_locator: str):
        av = _import_av()
        if av is None:
            raise CaptureError("PyAV (av) is not installed")
        try:
            return av.open(credentialed_locator, options=_av_options(options))
        except Exception as exc:
            raise CaptureError(f"cannot open RTSP stream: {exc}") from exc

    def probe_stream(
        self, locator: str, options: dict[str, Any], credentialed_locator: str
    ) -> dict[str, Any]:
        try:
            container = self._open(options, credentialed_locator)
        except CaptureError as exc:
            return _probe(False, str(exc))
        try:
            stream = container.streams.video[0]
            fps = float(stream.average_rate) if stream.average_rate else None
            duration_ms = int(container.duration / 1000) if container.duration else None
            return {
                "available": True,
                "message": None,
                "width": stream.width or None,
                "height": stream.height or None,
                "fps": fps,
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            return _probe(False, f"stream probe failed: {exc}")
        finally:
            container.close()

    def open_stream(
        self, locator: str, options: dict[str, Any], credentialed_locator: str
    ) -> _AvFrameStream:
        return _AvFrameStream(self._open(options, credentialed_locator))

    def grab(
        self, locator: str, options: dict[str, Any], credentialed_locator: str
    ) -> Any:
        container = self._open(options, credentialed_locator)
        try:
            for frame in container.decode(video=0):
                return frame.to_image()
            raise StreamEnded("stream ended before first frame")
        except CaptureError:
            raise
        except Exception as exc:
            raise StreamError(f"frame grab failed: {exc}") from exc
        finally:
            container.close()

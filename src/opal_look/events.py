"""OPAL event bus publication: two ZeroMQ frames [topic, JSON BusEvent].

Disabled by default; best-effort bounded queue with drop/rate-limit
counters and a topic allowlist. Transport is provisioned out of band via
OPAL_LOOK_EVENT_TRANSPORT. Never blocks inference.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Protocol


class EventPublisher(Protocol):
    def publish(self, topic: str, session_id: str | None, data: dict[str, Any]) -> None: ...
    def stats(self) -> dict[str, int]: ...
    def close(self) -> None: ...


class NullPublisher:
    def publish(self, topic: str, session_id: str | None, data: dict[str, Any]) -> None:
        return

    def stats(self) -> dict[str, int]:
        return {"published": 0, "dropped": 0, "rate_limited": 0, "queue_depth": 0}

    def close(self) -> None:
        return


class ZmqPublisher:
    def __init__(self, transport: str, queue_capacity: int = 256,
                 rate_per_second: float = 50.0) -> None:
        import zmq

        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUSH)
        self._sock.connect(transport)
        self._queue: queue.Queue = queue.Queue(maxsize=queue_capacity)
        self._rate = rate_per_second
        self._tokens = rate_per_second
        self._last_refill = time.monotonic()
        self._stats = {"published": 0, "dropped": 0, "rate_limited": 0}
        self._closed = False
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def publish(self, topic: str, session_id: str | None, data: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait((topic, session_id, data))
        except queue.Full:
            self._stats["dropped"] += 1

    def _take_token(self) -> bool:
        now = time.monotonic()
        self._tokens = min(self._rate, self._tokens + (now - self._last_refill) * self._rate)
        self._last_refill = now
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False

    def _drain(self) -> None:
        while not self._closed:
            try:
                topic, session_id, data = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if not self._take_token():
                self._stats["rate_limited"] += 1
                continue
            envelope = {
                "topic": topic,
                "session_id": session_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": data,
            }
            try:
                self._sock.send_multipart(
                    [topic.encode("utf-8"), json.dumps(envelope).encode("utf-8")],
                    flags=__import__("zmq").NOBLOCK,
                )
                self._stats["published"] += 1
            except Exception:
                self._stats["dropped"] += 1

    def stats(self) -> dict[str, int]:
        return {**self._stats, "queue_depth": self._queue.qsize()}

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close(linger=0)
        except Exception:
            pass


def make_publisher(app_settings, transport: str | None) -> EventPublisher:
    """Factory: real ZMQ publisher iff enabled + provisioned + allowlisted topics."""
    if (
        getattr(app_settings, "events_enabled", False)
        and transport
        and getattr(app_settings, "event_topics_allowlist", None)
    ):
        return ZmqPublisher(
            transport,
            queue_capacity=getattr(app_settings, "event_queue_capacity", 256),
            rate_per_second=getattr(app_settings, "event_rate_limit_per_second", 50.0),
        )
    return NullPublisher()


def allowed(topic: str, app_settings) -> bool:
    allowlist = getattr(app_settings, "event_topics_allowlist", None) or []
    return topic in allowlist


def publish_event(app, store, topic: str, session_id: str | None, data: dict) -> None:
    """Single publication entry point: enforces enabled + allowlist, lazily
    provisions the transport-backed publisher."""
    from .settings import effective_settings

    app_settings = effective_settings(store)
    if not getattr(app_settings, "events_enabled", False) or not allowed(topic, app_settings):
        return
    publisher = getattr(app.state, "event_publisher", None)
    if publisher is None:
        publisher = make_publisher(app_settings, app.state.event_transport)
        app.state.event_publisher = publisher
    publisher.publish(topic, session_id, data)

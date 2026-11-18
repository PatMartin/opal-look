"""Opt-in bridge: consume detection SSE, publish normalized Event envelopes.

The bridge is an SSE client of this service's
``GET /api/v1/stream/{id}/events`` surface and an Event publisher against
an OPAL Event service (``POST /api/v1/events/``, EventInput envelope —
see vendor/opal-api/opal_event.yaml). All interpretation lives at this
boundary: per-camera filters, cooldown, stable event identity,
deduplication across reconnect/replay, and bounded publish retries. The
stream runtime itself stays interpretation-free.

Dedup semantics: SSE ``id:`` is the per-run event sequence. On reconnect
the bridge resumes with ``Last-Event-ID`` and the runtime replays
buffered events; replayed ``(stream_id, seq)`` keys are suppressed and
each publish uses a deterministic UUIDv5 event id, so a replay can never
produce a second Event.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

log = logging.getLogger("opal_look.event_bridge")

_EVENT_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://opal.ai/look/event-bridge")
_DEDUP_BOUND = 8192
_TOPIC_BAD = re.compile(r"[^a-z0-9_.-]+")


@dataclass
class CameraFilter:
    """Per-camera publish policy. ``pattern`` is a fnmatch glob on the
    stream's user-chosen name (``"*"`` matches everything)."""
    pattern: str = "*"
    min_confidence: float = 0.0
    class_names: set[str] | None = None      # None -> all classes
    cooldown_seconds: float = 0.0

    def allows(self, det: dict[str, Any]) -> bool:
        if det["confidence"] < self.min_confidence:
            return False
        if self.class_names is not None and \
                det["class_name"] not in self.class_names:
            return False
        return True


@dataclass
class BridgeConfig:
    """Opt-in bridge configuration; nothing bridges unless constructed."""
    look_url: str
    event_url: str
    stream_id: str                          # run id or active name alias
    look_token: str | None = None
    event_token: str | None = None
    source: str = "opal-look"
    topic_prefix: str = "look.detection"
    filters: list[CameraFilter] = field(default_factory=list)
    # SSE reconnect: exponential backoff capped at backoff_max; give up
    # after max_reconnects (None = retry forever while the stream lives).
    reconnect_backoff: float = 1.0
    reconnect_backoff_max: float = 30.0
    max_reconnects: int | None = None
    # Publish: bounded attempts, then the event is dropped + counted.
    publish_attempts: int = 4
    publish_backoff: float = 0.25
    timeout: float = 30.0


def _topic_for(camera: str, prefix: str) -> str:
    cam = _TOPIC_BAD.sub("_", camera.lower()).strip("._-") or "stream"
    return f"{prefix}.{cam}"


def _event_id(stream_id: str, seq: int) -> str:
    """Deterministic id: replays/reconnects map to the same Event id."""
    return str(uuid.uuid5(_EVENT_NS, f"{stream_id}:{seq}"))


def iter_sse(lines: Iterable[str]) -> Iterable[tuple[int | None, str, str]]:
    """Parse an SSE byte stream into (id, event, data) tuples."""
    ev_id: str | None = None
    ev_type: str | None = None
    data_parts: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        if not line:
            if ev_type is not None:
                yield (int(ev_id) if ev_id is not None else None,
                       ev_type, "\n".join(data_parts))
            ev_id, ev_type, data_parts = None, None, []
            continue
        if line.startswith(":"):
            continue                          # heartbeat comment
        field_name, _, value = line.partition(":")
        value = value.lstrip(" ")
        if field_name == "id":
            ev_id = value
        elif field_name == "event":
            ev_type = value
        elif field_name == "data":
            data_parts.append(value)


class EventBridge:
    """Consumes one stream's detection SSE; publishes normalized Events."""

    def __init__(self, config: BridgeConfig,
                 look_client: httpx.Client | None = None,
                 event_client: httpx.Client | None = None):
        self.cfg = config
        headers = {}
        if config.look_token:
            headers["Authorization"] = f"Bearer {config.look_token}"
        self._look = look_client or httpx.Client(
            base_url=config.look_url, headers=headers, timeout=None)
        eh = {}
        if config.event_token:
            eh["Authorization"] = f"Bearer {config.event_token}"
        self._event = event_client or httpx.Client(
            base_url=config.event_url, headers=eh,
            timeout=config.timeout)
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque(maxlen=_DEDUP_BOUND)
        self._last_publish_at: dict[str, float] = {}
        self.last_seq: int | None = None
        self.stream_id: str | None = config.stream_id
        self._camera: str | None = None
        self.published = 0
        self.dropped = 0
        self.suppressed = 0

    # -- interpretation (bridge boundary) ------------------------------------

    def _filter_for(self, camera: str) -> CameraFilter:
        for f in self.cfg.filters:
            if fnmatch.fnmatchcase(camera, f.pattern):
                return f
        return CameraFilter()

    def interpret(self, camera: str, seq: int,
                  data: dict[str, Any]) -> dict[str, Any] | None:
        """Raw detection SSE -> EventInput envelope, or None to suppress."""
        policy = self._filter_for(camera)
        detections = [d for d in data.get("detections", [])
                      if policy.allows(d)]
        if not detections:
            self.suppressed += 1
            return None
        if policy.cooldown_seconds > 0:
            last = self._last_publish_at.get(camera, 0.0)
            if time.monotonic() - last < policy.cooldown_seconds:
                self.suppressed += 1
                return None
        top = max(detections, key=lambda d: d["confidence"])
        return {
            "id": _event_id(self.stream_id or camera, seq),
            "topic": _topic_for(camera, self.cfg.topic_prefix),
            "source": self.cfg.source,
            "data": {
                "camera": camera,
                "stream_id": self.stream_id,
                "frame": data.get("frame"),
                "sse_seq": seq,
                "detections": detections,
                "top_class": top["class_name"],
                "top_confidence": top["confidence"],
                "count": len(detections),
            },
        }

    # -- publication ----------------------------------------------------------

    def publish(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Bounded retry on transient failure; returns receipt or None."""
        delay = self.cfg.publish_backoff
        for attempt in range(self.cfg.publish_attempts):
            try:
                resp = self._event.post("/api/v1/events/", json=event)
            except httpx.HTTPError as exc:
                log.warning("event publish transport error: %s", exc)
                resp = None
            if resp is not None and resp.status_code == 202:
                self.published += 1
                return resp.json()
            if resp is not None and 400 <= resp.status_code < 500 \
                    and resp.status_code != 429:
                log.warning("event publish rejected %s: %s",
                            resp.status_code, resp.text[:200])
                break                       # 4xx won't heal on retry
            if attempt + 1 < self.cfg.publish_attempts:
                time.sleep(delay)
                delay = min(delay * 2, 5.0)
        self.dropped += 1
        return None

    # -- SSE consumption -------------------------------------------------------

    def handle_event(self, seq: int | None, etype: str,
                     data: dict[str, Any],
                     camera: str | None = None) -> dict[str, Any] | None:
        """One parsed SSE event. Returns the receipt when published."""
        if etype != "detection" or seq is None:
            return None
        dedup_key = f"{self.stream_id}:{seq}"
        if dedup_key in self._seen:
            self.suppressed += 1
            return None                     # replayed after reconnect
        self._seen.add(dedup_key)
        self._seen_order.append(dedup_key)
        while len(self._seen) > _DEDUP_BOUND:
            self._seen.discard(self._seen_order.popleft())
        cam = camera or self._camera or self.stream_id or "stream"
        event = self.interpret(cam, seq, data)
        if event is None:
            return None
        self._last_publish_at[camera] = time.monotonic()
        return self.publish(event)

    def _consume(self, resp: httpx.Response) -> str:
        """Iterate SSE until terminal/dropped. Returns 'terminal'|'closed'."""
        for seq, etype, payload in iter_sse(resp.iter_lines()):
            if seq is not None:
                self.last_seq = seq
            if etype == "detection" and payload:
                self.handle_event(seq, etype, json.loads(payload),
                                  camera=self._camera)
            if etype in ("terminal", "dropped"):
                return "terminal"
        return "closed"

    def _resolve_identity(self) -> None:
        """Resolve run id -> user-chosen name once (StreamStatus.name)."""
        try:
            resp = self._look.get(
                f"/api/v1/stream/{self.cfg.stream_id}")
            if resp.status_code == 200:
                body = resp.json()
                self.stream_id = body.get("stream_id", self.cfg.stream_id)
                self._camera = body.get("name") or self.stream_id
        except httpx.HTTPError:
            self._camera = self.cfg.stream_id
        if self._camera is None:
            self._camera = self.cfg.stream_id

    def run(self) -> None:
        """Connect, consume, reconnect. Bounded by cfg.max_reconnects."""
        self._resolve_identity()
        camera = self._camera or self.cfg.stream_id
        attempts = 0
        backoff = self.cfg.reconnect_backoff
        while True:
            headers = ({f"Last-Event-ID": str(self.last_seq)}
                       if self.last_seq is not None else {})
            try:
                with self._look.stream(
                        "GET",
                        f"/api/v1/stream/{self.cfg.stream_id}/events",
                        headers=headers) as resp:
                    if resp.status_code == 409:
                        log.warning("stale Last-Event-ID; resuming fresh")
                        self.last_seq = None
                        continue
                    resp.raise_for_status()
                    attempts = 0
                    backoff = self.cfg.reconnect_backoff
                    if self._consume(resp) == "terminal":
                        return
            except httpx.HTTPError as exc:
                log.warning("SSE connection failed: %s", exc)
            attempts += 1
            if self.cfg.max_reconnects is not None \
                    and attempts > self.cfg.max_reconnects:
                log.error("bridge gave up after %d reconnects", attempts)
                return
            time.sleep(backoff)
            backoff = min(backoff * 2, self.cfg.reconnect_backoff_max)


def run_bridge(config: BridgeConfig) -> EventBridge:
    """Construct + run (blocking). Entry point for the CLI verb."""
    bridge = EventBridge(config)
    bridge.run()
    return bridge

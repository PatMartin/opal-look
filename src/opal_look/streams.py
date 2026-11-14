"""Ephemeral in-memory RTSP stream runtimes.

One ``StreamRuntime`` per admitted stream (Command/State Machine):
a capture-adapter decode pump (Adapter), an optional inference stage
(Strategy over EngineAdapter), and a per-stream event hub (Observer)
feeding SSE watchers and MJPEG viewers. Streams are never persisted —
a service restart clears them, matching the contract's ephemeral model.

State machine: starting -> running -> stopping -> stopped | failed.
The decode pump is shared: viewers/snapshots never start a second
decode pass.
"""

from __future__ import annotations

import io
import queue
import threading
import time
import uuid
from collections import deque
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .capture import LiveFramePump, capture_adapter_for
from .timeutil import now_iso

TERMINAL_STATES = ("stopped", "failed")


def redact_source(uri: str) -> str:
    """RTSP URI without userinfo; credentials are never echoed."""
    parts = urlsplit(uri)
    host = parts.hostname or ""
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    authority = host
    if parts.port:
        authority += f":{parts.port}"
    return urlunsplit((parts.scheme, authority, parts.path,
                       parts.query, parts.fragment))


def _jpeg(image) -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=80)
    return buf.getvalue()


class StreamRuntime:
    """One ephemeral stream: decode pump + optional inference + events."""

    def __init__(
        self,
        *,
        stream_id: str | None = None,
        source: str,
        engine=None,
        model_id: str | None = None,
        confidence: float = 0.25,
        device_id: str | None = None,
        engine_options: dict[str, Any] | None = None,
        annotate: bool = False,
        buffer_policy: str = "drop-oldest",
        buffer_size: int = 5,
        sse_buffer: int = 256,
    ) -> None:
        self.stream_id = stream_id or f"strm_{uuid.uuid4().hex[:16]}"
        self.mode = "inference" if engine is not None else "video"
        self._source = source
        self.source_redacted = redact_source(source)
        self._engine = engine
        self.engine_id = engine.engine_id if engine else None
        self.model_id = model_id
        self.confidence = confidence
        self.device_id = device_id
        self.engine_options = engine_options or {}
        self.annotate = annotate
        self.buffer_policy = buffer_policy
        self.buffer_size = buffer_size

        self.status = "starting"
        self.started_at = now_iso()
        self._started_monotonic = time.monotonic()
        self.last_frame_at: str | None = None
        self.frames_received = 0
        self.frames_processed = 0
        self.frames_dropped = 0
        self._error: dict[str, Any] | None = None
        self._infer_ms: list[float] = []

        self._frame_no = 0
        self._latest: Any = None           # plain PIL frame
        self._latest_annotated: Any = None  # annotated copy (inference+annotate)
        self._pump: LiveFramePump | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # Observer hub: bounded replay buffer + subscriber queues.
        self._event_seq = 0
        self._events: deque[tuple[int, str, dict]] = deque(maxlen=sse_buffer)
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"stream-{self.stream_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.status in TERMINAL_STATES or self.status == "stopping":
            return
        self.status = "stopping"
        self._emit("status", {"status": "stopping"})
        self._stop.set()
        if self._pump is not None:
            self._pump.close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.status = "stopped"
        self._emit("terminal", {"status": "stopped"})

    def _run(self) -> None:
        try:
            adapter = capture_adapter_for("rtsp")
            if adapter is None:
                raise RuntimeError("no rtsp capture adapter installed")
            frames = adapter.open_stream(self._source, {}, self._source)
            self._pump = LiveFramePump(
                frames, capacity=self.buffer_size,
                policy=self.buffer_policy).start()
            self.status = "running"
            self._emit("status", {"status": "running"})
            while not self._stop.is_set():
                try:
                    frame = self._pump.get(timeout=0.5)
                except queue.Empty:
                    continue
                self.frames_received += 1
                detections: list[dict] = []
                infer_ms: float | None = None
                if self._engine is not None:
                    t0 = time.perf_counter()
                    result = self._engine.predict(
                        image=frame, model_id=self.model_id,
                        confidence=self.confidence,
                        device_id=self.device_id,
                        engine_options=self.engine_options,
                        include_native=False)
                    infer_ms = (time.perf_counter() - t0) * 1000
                    self._infer_ms.append(infer_ms)
                    detections = result["detections"]
                self._publish_frame(frame, detections, infer_ms)
                self.frames_processed += 1
                self.frames_dropped += self._pump.take_dropped()
            if self.status != "stopping":
                self.status = "stopped"
        except Exception as exc:
            if self.status == "stopping":
                return
            self.status = "failed"
            self._error = {"code": "stream_failed", "message": str(exc)}
            self._emit("terminal", {"status": "failed",
                                    "error": {"code": "stream_failed",
                                              "message": str(exc)}})

    # -- frames --------------------------------------------------------------

    def _annotate(self, image, detections: list[dict]):
        from PIL import ImageDraw

        out = image.convert("RGB").copy()
        draw = ImageDraw.Draw(out)
        for det in detections:
            x1, y1, x2, y2 = det["box"]
            draw.rectangle([x1, y1, x2, y2], outline=(255, 64, 64), width=2)
            draw.text((x1, max(0, y1 - 10)),
                      f"{det['class_name']} {det['confidence']:.2f}",
                      fill=(255, 64, 64))
        return out

    def _publish_frame(self, frame, detections, infer_ms) -> None:
        with self._lock:
            self._frame_no += 1
            self._latest = frame
            self.last_frame_at = now_iso()
            if self.annotate and detections is not None:
                self._latest_annotated = self._annotate(frame, detections)
            self._emit("frame", {"frame": self._frame_no,
                                 "detections": len(detections),
                                 "inference_ms": infer_ms})
            if self.mode == "inference" and detections:
                self._emit("detection", {"frame": self._frame_no,
                                         "detections": detections,
                                         "processing_ms": infer_ms})

    def latest_jpeg(self, annotated: bool = False) -> bytes | None:
        with self._lock:
            img = self._latest_annotated if annotated else self._latest
            if img is None:
                return None
            return _jpeg(img)

    # -- events (Observer) ----------------------------------------------------

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        self._event_seq += 1
        event = (self._event_seq, event_type, data)
        self._events.append(event)
        for sub in list(self._subs):
            try:
                sub.put_nowait(event)
            except queue.Full:
                self._subs.remove(sub)

    def subscribe(self, last_event_id: int | None) -> queue.Queue:
        """Replay buffered events newer than last_event_id, then live tail.
        Raises ValueError('stale') when the requested ID fell off the buffer."""
        sub: queue.Queue = queue.Queue(maxsize=1024)
        with self._lock:
            if last_event_id is not None:
                oldest = (self._event_seq - len(self._events)
                          if self._events else 0)
                if last_event_id < oldest or last_event_id < 0:
                    raise ValueError("stale")
                for seq, etype, data in self._events:
                    if seq > last_event_id:
                        sub.put_nowait((seq, etype, data))
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: queue.Queue) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    # -- contract views --------------------------------------------------------

    def capabilities_list(self) -> list[str]:
        caps = ["video", "snapshot", "metrics", "stream_events"]
        if self.mode == "inference":
            caps.append("detections")
            if self.annotate:
                caps.append("annotations")
        return caps

    def status_dict(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "mode": self.mode,
            "engine_id": self.engine_id,
            "model_id": self.model_id,
            "status": self.status,
            "started_at": self.started_at,
            "last_frame_at": self.last_frame_at,
            "frames_received": self.frames_received,
            "frames_processed": self.frames_processed,
            "error": {"error": self._error} if self._error else None,
            "supports_video": True,
            "events_url": f"/api/v1/stream/{self.stream_id}/events",
            "video_url": f"/api/v1/stream/{self.stream_id}/video",
            "source_redacted": self.source_redacted,
            "capabilities": self.capabilities_list(),
        }

    def metrics_dict(self) -> dict[str, Any]:
        uptime = max(0.0, time.monotonic() - self._started_monotonic)
        infer = (sum(self._infer_ms) / len(self._infer_ms)
                 if self.mode == "inference" and self._infer_ms else None)
        return {
            "stream_id": self.stream_id,
            "mode": self.mode,
            "uptime_seconds": round(uptime, 3),
            "frames_received": self.frames_received,
            "frames_processed": self.frames_processed,
            "frames_dropped": self.frames_dropped,
            "input_fps": round(self.frames_received / uptime, 2)
            if uptime else 0.0,
            "output_fps": round(self.frames_processed / uptime, 2)
            if uptime else 0.0,
            "queue_depth": self._pump.queue_depth if self._pump else 0,
            "queue_capacity": self.buffer_size,
            "decode_latency_ms": None,
            "inference_latency_ms": round(infer, 2) if infer is not None else None,
            "last_frame_at": self.last_frame_at,
        }

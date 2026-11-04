"""Monitor runtime: persistent desired-state pipeline workers (v1.5).

A Monitor is durable configuration (DB row); enabled monitors spawn a
private worker thread that consumes the source through LiveFramePump and
runs the stored pipeline per frame. Produced observations go to a bounded
per-monitor ring buffer (tailed by the SSE endpoint) and are persisted
only when the monitor's retention opts in. Restart policy governs
crash/exits: on_failure (bounded backoff restarts), always, never.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import deque
from typing import Any

from .engines import ENGINE_REGISTRY, model_runtime
from .pipeline_exec import _stage_list, run_pipeline
from .timeutil import now_iso

_OBS_BUFFER_MAX = 64          # transient SSE tail, not durable replay
_RESTART_MAX = 3              # bounded consecutive restarts
_RESTART_BACKOFF_S = 0.05     # fake-friendly backoff


def monitor_read(store, row: sqlite3.Row, runtime=None) -> dict[str, Any]:
    """v1.5 Monitor resource; state derived from desired state + runtime."""
    enabled = bool(row["enabled"])
    state = "disabled"
    if enabled:
        if runtime is not None and runtime.alive:
            state = "running"
        elif row["last_failure"]:
            state = "failed"
        else:
            state = "starting"
    return {
        "id": row["monitor_id"],
        "name": row["name"],
        "source_id": row["source_id"],
        "pipeline_id": row["pipeline_id"],
        "enabled": enabled,
        "restart_policy": row["restart_policy"],
        "options": json.loads(row["options"]),
        "retention": json.loads(row["retention"]),
        "conditions": json.loads(row["conditions"]),
        "publish_events": bool(row["publish_events"]),
        "state": state,
        "created_at": row["created_at"],
        "last_observation_at": row["last_observation_at"],
        "last_failure": json.loads(row["last_failure"]) if row["last_failure"] else None,
    }


class MonitorRuntime:
    """Per-monitor in-process runtime: worker thread + observation buffer."""

    def __init__(self, store, monitor_id: str) -> None:
        self.store = store
        self.monitor_id = monitor_id
        self.alive = False
        self.observations: deque = deque(maxlen=_OBS_BUFFER_MAX)
        self.condition_events: deque = deque(maxlen=_OBS_BUFFER_MAX)
        self.event_log: deque = deque(maxlen=256)  # (seq, kind, payload)
        self.event_seq = 0
        self.cond_state: dict = {}
        self.updated = threading.Event()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._restarts = 0

    def emit(self, kind: str, payload: dict) -> int:
        self.event_seq += 1
        self.event_log.append((self.event_seq, kind, payload))
        self.updated.set()
        return self.event_seq

    def start(self) -> None:
        if self.alive:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"monitor-{self.monitor_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.updated.set()
        self.alive = False

    def _safe_update(self, fields) -> None:
        if self._stop.is_set():
            return
        try:
            self.store.monitors.update(self.monitor_id, fields)
        except Exception:
            pass  # store may be closed during teardown

    def _fail(self, message: str) -> None:
        self.alive = False
        self._safe_update({"last_failure": json.dumps({
            "code": "monitor_failed", "message": message,
            "request_id": None, "transaction_id": None})})
        self.updated.set()

    def _run(self) -> None:
        from .capture import (CaptureError, CredentialUnavailable,
                              LiveFramePump, capture_adapter_for,
                              credentialed_locator)
        from .errors import ApiError

        try:
            row = self.store.monitors.get(self.monitor_id)
            if row is None or not row["enabled"]:
                return
            src = self.store.sources.get(row["source_id"])
            pipeline = self.store.pipelines.get(row["pipeline_id"])
            if src is None or pipeline is None or not src["enabled"]:
                self._fail("source or pipeline is missing/disabled")
                return
            adapter = capture_adapter_for(src["type"])
            if adapter is None or src["type"] not in ("rtsp", "http", "camera"):
                self._fail(f"source kind {src['type']!r} is not a live stream")
                return
            installed, message = adapter.installed()
            if not installed:
                self._fail(f"capture backend unavailable: {message}")
                return
            try:
                cred = credentialed_locator(src["locator"], src["credential_ref"])
            except CredentialUnavailable as exc:
                self._fail(f"credential unavailable: {exc}")
                return
            try:
                stream = adapter.open_stream(
                    src["locator"], json.loads(src["source_options"]), cred)
            except CaptureError as exc:
                self._fail(f"capture open failed: {exc}")
                return

            pump = LiveFramePump(stream).start()
            motion_states: dict = {}
            retention = json.loads(row["retention"] or "{}")
            self.alive = True
            self._restarts = 0
            try:
                while not self._stop.is_set():
                    try:
                        frame = pump.get(timeout=0.25)
                    except Exception:
                        if self._stop.is_set():
                            break
                        self._fail("frame stream ended")
                        break
                    try:
                        result = run_pipeline(
                            self.store, pipeline, frame,
                            source_id=src["source_id"], media_id=None,
                            frame_index=None, transaction_id=self.monitor_id,
                            request_id=self.monitor_id,
                            motion_states=motion_states)
                    except ApiError as exc:
                        self._fail(str(exc))
                        break
                    self.observations.extend(result["observations"])
                    for obs in result["observations"]:
                        self.emit("observation", obs)
                    self.updated.set()
                    now = now_iso()
                    # inline condition evaluation
                    try:
                        from .condition_eval import evaluate_conditions
                        zones = json.loads(src["zones"] or "[]")
                        tracking = any(
                            model_runtime(self.store, m).get("tracking")
                            for st in _stage_list(self.store, pipeline)
                            if st.kind == "inference"
                            for m in [self.store.models.get(st.model_id)]
                            if m is not None)
                        matched = evaluate_conditions(
                            _to_conds(row["conditions"]), result["observations"],
                            zones, self.cond_state, tracking)
                        for ev in matched:
                            ev["monitor_id"] = self.monitor_id
                            self.condition_events.append(ev)
                            self.emit("condition_match", ev)
                            if _cond_by_id(row, ev["monitor_condition"]).capture_on_match:
                                try:
                                    import io as _io
                                    from .media import create_media
                                    buf = _io.BytesIO()
                                    frame.convert("RGB").save(buf, "JPEG")
                                    create_media(
                                        self.store, buf.getvalue(),
                                        kind="snapshot", origin="monitor",
                                        filename="monitor-capture.jpg",
                                        content_type="image/jpeg",
                                        monitor_id=self.monitor_id)
                                except Exception:
                                    pass
                            clip = _cond_by_id(row, ev["monitor_condition"]).clip_on_match
                            if clip:
                                ev["clip_unsupported"] = True
                                ev["clip_reason"] = "no video decoder installed"
                    except Exception:
                        pass
                    self._safe_update({"last_observation_at": now})
                    if retention.get("persist_observations"):
                        ttl = retention.get("ttl_seconds")
                        from .timeutil import iso, parse_iso
                        from datetime import timedelta
                        expires = (iso(parse_iso(now) + timedelta(seconds=ttl))
                        if ttl else None)
                        try:
                            with self.store.write_txn():
                                for obs in result["observations"]:
                                    obs["monitor_id"] = self.monitor_id
                                    self.store.observations.insert(obs, expires)
                        except Exception:
                            pass  # teardown: store closed mid-write
            finally:
                pump.close()
                self.alive = False
        except Exception as exc:  # noqa: BLE001
            self._fail(f"monitor worker error: {exc}")

        # restart policy
        try:
            row = self.store.monitors.get(self.monitor_id)
        except Exception:
            return  # store closed during teardown
        policy = (row["restart_policy"] if row else "never")
        if (not self._stop.is_set() and row is not None and row["enabled"]
                and policy != "never" and self._restarts < _RESTART_MAX):
            self._restarts += 1
            time.sleep(_RESTART_BACKOFF_S)
            self.start()


def start_monitor(store, runtime_registry: dict, monitor_id: str) -> None:
    runtime = runtime_registry.get(monitor_id)
    if runtime is None:
        runtime = MonitorRuntime(store, monitor_id)
        runtime_registry[monitor_id] = runtime
    runtime.start()


def stop_monitor(runtime_registry: dict, monitor_id: str) -> None:
    runtime = runtime_registry.get(monitor_id)
    if runtime is not None:
        runtime.stop()


def recover_monitors(store, runtime_registry: dict) -> list[str]:
    """On startup: enabled monitors (re)start their workers."""
    started = []
    for row in store.monitors.list():
        if row["enabled"]:
            start_monitor(store, runtime_registry, row["monitor_id"])
            started.append(row["monitor_id"])
    return started


def validate_monitor_refs(store, source_id: str, pipeline_id: str,
                          conditions: list | None = None) -> None:
    """Dependency validation shared by create/patch."""
    from .errors import ApiError

    src = store.sources.get(source_id)
    if src is None:
        raise ApiError(404, f"Unknown source: {source_id!r}")
    pipe = store.pipelines.get(pipeline_id)
    if pipe is None:
        raise ApiError(404, f"Unknown pipeline: {pipeline_id!r}")
    for st in _stage_list(store, pipe):
        if st.kind != "inference":
            continue
        mrow = store.models.get(st.model_id)
        if mrow is None:
            raise ApiError(422, f"Pipeline stage {st.id!r}: model "
                                f"{st.model_id!r} is not registered.")
        rt = model_runtime(store, mrow)
        if st.task not in rt["tasks"]:
            raise ApiError(422, f"Pipeline stage {st.id!r}: task "
                                f"{st.task!r} unsupported by model.")
        if ENGINE_REGISTRY.get(rt["engine_id"]) is None:
            raise ApiError(503, f"Pipeline stage {st.id!r}: engine "
                                f"{rt['engine_id']!r} is not installed.")
    if conditions:
        from .condition_eval import validate_conditions_for_source
        errors = validate_conditions_for_source(store, src, conditions, pipe)
        if errors:
            raise ApiError(422, "; ".join(errors))


def _cond_by_id(row, cid):
    import json as _j
    for c in _j.loads(row["conditions"] or "[]"):
        if c["id"] == cid:
            return c
    return {}


def _to_conds(raw):
    from .schemas import MonitorCondition
    import json as _j
    if isinstance(raw, str):
        raw = _j.loads(raw or "[]")
    return [c if isinstance(c, MonitorCondition) else MonitorCondition(**c)
            for c in (raw or [])]

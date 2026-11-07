"""Recording runtime (v1.5, step 23): explicit independent recordings.

A Recording captures a live source's frames to a bounded on-disk MJPEG
byte stream, finalized into a unified Media row (kind=recording,
origin=recording) carrying recording provenance. Recording is started
only by explicit POST — viewers/disconnects never start/stop one.
Duration and disk bounds stop/fail honestly; interrupted recordings at
restart are failed and their partial blobs removed.
"""

from __future__ import annotations

import io
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .errors import ApiError
from .media import create_media, media_dir
from .timeutil import now_iso

_LIVE_TYPES = {"rtsp", "http", "camera"}


def recording_read(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["recording_id"],
        "source_id": row["source_id"],
        "state": row["state"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "media_id": row["media_id"],
        "artifact_id": (row["artifact_id"] if "artifact_id" in row.keys()
                        else None),
        "failure": (json.loads(row["failure"]) if row["failure"] else None),
    }


def _partial_path(store, recording_id: str) -> Path:
    return media_dir(store.data_dir) / f"rec-{recording_id}.mjpg"


def _fail(store, recording_id: str, code: str, message: str) -> None:
    store.recordings.update(recording_id, {
        "state": "failed", "finished_at": now_iso(),
        "failure": json.dumps({"code": code, "message": message,
                               "request_id": None, "transaction_id": None})})
    try:
        _partial_path(store, recording_id).unlink(missing_ok=True)
    except Exception:
        pass


def _finalize(store, recording_id: str, pipeline_id=None) -> None:
    """Stop-to-finalize: the partial MJPEG stream becomes unified Media."""
    partial = _partial_path(store, recording_id)
    row = store.recordings.get(recording_id)
    if row is None:
        return
    if not partial.exists() or partial.stat().st_size == 0:
        _fail(store, recording_id, "empty_recording",
              "recording produced no frames")
        return
    data = partial.read_bytes()
    media_id = create_media(
        store, data, kind="recording", origin="recording",
        filename=f"recording-{recording_id}.mjpeg",
        content_type="video/x-motion-jpeg",
        source_id=row["source_id"])
    # upstream: recording output is an Artifact of kind "video"
    mrow = store.media.get(media_id)
    artifact_id = f"art-{recording_id}"
    store.artifacts.insert({
        "artifact_id": artifact_id, "kind": "video",
        "mime_type": "video/x-motion-jpeg",
        "size_bytes": len(data), "created_at": now_iso(),
        "expires_at": mrow["expires_at"] if mrow is not None else now_iso(),
        "source_id": row["source_id"], "job_id": None,
        "path": mrow["path"] if mrow is not None else str(partial),
    })
    store.recordings.update(recording_id, {
        "state": "completed", "finished_at": now_iso(),
        "media_id": media_id, "artifact_id": artifact_id})
    try:
        partial.unlink(missing_ok=True)
    except Exception:
        pass


def recover_recordings(store, runtime: dict) -> None:
    """Interrupted recordings never produce partial media silently."""
    for row in store.recordings.list_active():
        _fail(store, row["recording_id"], "interrupted",
              "service restarted while the recording was active")


class RecordingRuntime:
    """One worker thread per recording; stop() is cooperative."""

    def __init__(self, store, recording_id: str, app=None) -> None:
        self.store = store
        self.recording_id = recording_id
        self._app = app
        self.alive = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.alive:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"rec-{self.recording_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 10.0) -> None:
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=timeout)

    def _run(self) -> None:
        from .capture import (CaptureError, CredentialUnavailable,
                              LiveFramePump, capture_adapter_for,
                              credentialed_locator)
        from .settings import effective_settings

        rid = self.recording_id
        try:
            row = self.store.recordings.get(rid)
            if row is None or row["state"] not in ("starting", "recording"):
                return
            src = self.store.sources.get(row["source_id"])
            if src is None or not src["enabled"]:
                _fail(self.store, rid, "source_unavailable",
                      "source missing or disabled")
                return
            adapter = capture_adapter_for(src["type"])
            if adapter is None or src["type"] not in _LIVE_TYPES:
                _fail(self.store, rid, "source_unavailable",
                      f"source kind {src['type']!r} cannot be recorded")
                return
            installed, message = adapter.installed()
            if not installed:
                _fail(self.store, rid, "capture_unavailable",
                      f"capture backend unavailable: {message}")
                return
            try:
                cred = credentialed_locator(src["locator"], src["credential_ref"])
            except CredentialUnavailable as exc:
                _fail(self.store, rid, "credential_unavailable", str(exc))
                return
            try:
                stream = adapter.open_stream(
                    src["locator"], json.loads(src["source_options"]), cred)
            except CaptureError as exc:
                _fail(self.store, rid, "capture_open_failed", str(exc))
                return

            output = json.loads(row["output_json"] or "null") or {}
            annotated = bool(output.get("annotated")) and row["pipeline_id"]
            pipeline = (self.store.pipelines.get(row["pipeline_id"])
                        if row["pipeline_id"] else None)
            if annotated and pipeline is None:
                _fail(self.store, rid, "pipeline_unavailable",
                      "annotated recording pipeline is missing")
                return
            pipeline = pipeline or (self.store.pipelines.get(
                row["pipeline_id"]) if row["pipeline_id"] else None)

            self.store.recordings.update(rid, {
                "state": "recording", "started_at": now_iso()})
            self.alive = True
            pump = LiveFramePump(stream).start()
            cap_bytes = effective_settings(self.store).recording_max_bytes
            duration_cap = row["max_duration_seconds"]
            started_mono = time.monotonic()
            motion_states: dict = {}
            partial = _partial_path(self.store, rid)
            n_frames = n_bytes = 0
            try:
                with partial.open("wb") as fh:
                    while not self._stop.is_set():
                        if (duration_cap is not None
                                and time.monotonic() - started_mono
                                >= duration_cap):
                            break  # duration cap -> finalize, not fail
                        try:
                            frame = pump.get(timeout=0.25)
                        except Exception:
                            break  # stream ended -> finalize what we have
                        img = frame
                        if pipeline is not None and annotated:
                            try:
                                result = __import__(
                                    "opal_look.pipeline_exec",
                                    fromlist=["run_pipeline"]).run_pipeline(
                                    self.store, pipeline, frame,
                                    source_id=src["source_id"],
                                    media_id=None, frame_index=n_frames,
                                    transaction_id=rid, request_id=rid,
                                    motion_states=motion_states)
                                img = result.get("_presentation") or frame
                            except ApiError:
                                pass  # un-annotated frame still records
                        buf = io.BytesIO()
                        img.convert("RGB").save(buf, "JPEG", quality=85)
                        data = buf.getvalue()
                        if n_bytes + len(data) > cap_bytes:
                            break  # disk bound -> finalize
                        fh.write(data)
                        n_bytes += len(data)
                        n_frames += 1
                        if n_frames % 5 == 0:
                            self.store.recordings.update(rid, {
                                "bytes_written": n_bytes,
                                "frames_written": n_frames})
            finally:
                pump.close()
                self.alive = False
            self.store.recordings.update(rid, {
                "bytes_written": n_bytes, "frames_written": n_frames,
                "state": "stopping"})
            _finalize(self.store, rid)
        except Exception as exc:  # noqa: BLE001
            try:
                _fail(self.store, rid, "recording_failed", str(exc))
            except Exception:
                pass


def start_recording(store, registry: dict, recording_id: str, app=None) -> None:
    rt = registry.get(recording_id)
    if rt is None:
        rt = RecordingRuntime(store, recording_id, app)
        registry[recording_id] = rt
    rt.start()


def stop_recording(registry: dict, recording_id: str) -> None:
    rt = registry.get(recording_id)
    if rt is not None:
        rt.stop()
        rt.join()


def validate_recording_refs(store, source_id: str, pipeline_id,
                            include_audio: bool, output) -> None:
    src = store.sources.get(source_id)
    if src is None:
        raise ApiError(404, f"Unknown source: {source_id!r}")
    if src["type"] not in _LIVE_TYPES:
        raise ApiError(422, f"source kind {src['type']!r} cannot be recorded")
    if not src["enabled"]:
        raise ApiError(503, f"Source {source_id!r} is unavailable.")
    if include_audio:
        raise ApiError(422, "audio capture is not supported by this backend")
    if pipeline_id is not None:
        if store.pipelines.get(pipeline_id) is None:
            raise ApiError(404, f"Unknown pipeline: {pipeline_id!r}")
    if output is not None and output.format in ("mp4", "webm", "png"):
        raise ApiError(422, f"recording output {output.format!r} requires a "
                            "video encoder (not installed)")

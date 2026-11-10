"""Finite job runtime (v1.5, step 22): video_analysis and media_export.

A Job is a bounded asynchronous unit of work: frames come only from
finite inputs (media blobs, finite sources — never live streams), a
validated pipeline executes per frame, and outputs are unified Media
rows carrying job provenance. Cancel is cooperative (a per-job Event
checked between frames); concurrency is bounded; restart marks
interrupted jobs honestly.
"""

from __future__ import annotations

import io
import json
import sqlite3
import threading
from typing import Any

from .errors import ApiError
from .media import create_media, media_dir
from .pipeline_exec import run_pipeline, _stage_list
from .timeutil import now_iso

_MAX_JOB_FRAMES = 300  # bounded full-video buffering


def job_read(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["job_id"],
        "kind": row["kind"],
        "state": row["state"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "progress": row["progress"],
        # produced media are mirrored as artifacts (art-{media_id})
        "artifact_ids": [
            f"art-{m}" for m in json.loads(row["media_ids"] or "[]")],
        "output_refs": (
            [
                {"kind": "artifact", "id": f"art-{m}", "content_url": f"/api/v1/artifact/art-{m}/content"}
                for m in json.loads(row["media_ids"] or "[]")
            ]
            if json.loads(row["media_ids"] or "[]")
            else None
        ),
        "failure": (json.loads(row["failure"]) if row["failure"] else None),
    }


def _job_fail(store, job_id: str, code: str, message: str) -> None:
    store.jobs.update(job_id, {
        "state": "failed", "ended_at": now_iso(),
        "failure": json.dumps({"code": code, "message": message,
                               "request_id": None, "transaction_id": None}),
    })


def _job_terminal(store, job_id: str, state: str) -> None:
    store.jobs.update(job_id, {"state": state, "ended_at": now_iso()})


def _read_blob(store, mrow) -> bytes:
    return (media_dir(store.data_dir) / mrow["media_id"]).read_bytes()


def _read_blob_file(src) -> bytes:
    """file/image sources: locator is a path — read it (bounded, no
    arbitrary-path escapes outside the data dir are allowed)."""
    from pathlib import Path
    p = Path(src["locator"])
    try:
        base = Path(src.get("data_dir", ".")).resolve() if hasattr(src, "get") else None
    except Exception:
        base = None
    if base is not None and base not in p.resolve().parents and p.resolve() != base:
        raise ApiError(422, "source path escapes the data directory")
    try:
        return p.read_bytes()
    except Exception:
        raise ApiError(503, "source file unavailable")


def _decode_frames(store, payload) -> list:
    """Resolve the job's finite frame set (bounded)."""

    frames: list = []
    if payload.get("media_id"):
        mrow = store.media.get(payload["media_id"])
        if mrow is None:
            raise ApiError(404, f"Unknown media: {payload['media_id']!r}")
        data = _read_blob(store, mrow)
        frames.extend(_decode_blob_frames(data, mrow["content_type"]))
    else:
        src = store.sources.get(payload["source_id"])
        if src is None:
            raise ApiError(404, f"Unknown source: {payload['source_id']!r}")
        if src["type"] not in ("media", "file", "image"):
            raise ApiError(422, f"source kind {src['type']!r} is not finite")
        mrow = store.media.get(json.loads(src["source_options"])["media_id"]) \
            if src["type"] == "media" else None
        if mrow is not None:
            data = _read_blob(store, mrow)
            frames.extend(_decode_blob_frames(data, mrow["content_type"]))
        else:
            from .analysis import acquire_frame
            img, _ = acquire_frame(store, src, None)
            frames.append(img)
    if len(frames) > _MAX_JOB_FRAMES:
        raise ApiError(422, f"input exceeds the {_MAX_JOB_FRAMES}-frame bound")
    return frames


def _decode_blob_frames(data: bytes, mime: str) -> list:
    from PIL import Image, ImageOps, ImageSequence
    buf = io.BytesIO(data)
    try:
        img = Image.open(buf)
    except Exception:
        raise ApiError(503, "video/image decoder unavailable for this media")
    frames = [ImageOps.exif_transpose(f).convert("RGB")
              for f in ImageSequence.Iterator(img)]
    return frames or [img.convert("RGB")]


class JobRuntime:
    """Bounded cooperative worker pool keyed by job."""

    def __init__(self, store, app=None) -> None:
        self.store = store
        self._app = app
        self.cancel_events: dict[str, threading.Event] = {}
        self.running: set[str] = set()
        self.waiting: set[str] = set()
        self._lock = threading.Lock()

    def start(self, job_id: str) -> None:
        cancel = self.cancel_events.setdefault(job_id, threading.Event())
        with self._lock:
            self.waiting.add(job_id)
        threading.Thread(target=self._run, args=(job_id, cancel),
                         name=f"job-{job_id}", daemon=True).start()

    def cancel(self, job_id: str) -> None:
        ev = self.cancel_events.setdefault(job_id, threading.Event())
        ev.set()

    def join(self, job_id: str, timeout: float = 10.0) -> None:
        # test helper: poll until the worker exits
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if job_id not in self.running and job_id not in self.waiting:
                    return
            time.sleep(0.02)

    def stop_all(self, timeout: float = 10.0) -> None:
        with self._lock:
            ids = list(self.running | self.waiting)
        for jid in ids:
            self.cancel(jid)
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if not self.running and not self.waiting:
                    return
            time.sleep(0.02)

    def _wait_for_slot(self, job_id: str, cancel: threading.Event) -> bool:
        """Bounded concurrency: hold the job 'queued' until a slot frees."""
        import time as _t
        from .settings import effective_settings
        while True:
            if cancel.is_set():
                _job_terminal(self.store, job_id, "cancelled")
                return False
            try:
                cap = effective_settings(self.store).max_jobs or 4
            except Exception:
                return False
            with self._lock:
                if len(self.running) < cap:
                    self.running.add(job_id)
                    return True
            _t.sleep(0.05)

    def _run(self, job_id: str, cancel: threading.Event) -> None:
        try:
            row = self.store.jobs.get(job_id)
            if row is None or row["state"] not in ("queued", "running"):
                return
            if not self._wait_for_slot(job_id, cancel):
                return
            payload = json.loads(row["payload_json"])
            self.store.jobs.update(job_id, {
                "state": "running", "started_at": now_iso()})
            try:
                self._execute(job_id, payload, cancel)
            except ApiError as exc:
                self._transition(job_id, cancel)
                self.store.jobs.update(
                    job_id, {"state": "failed", "ended_at": now_iso(),
                             "failure": json.dumps(
                                 {"code": exc.code or "job_failed",
                                  "message": str(exc),
                                  "request_id": None,
                                  "transaction_id": None})})
            except Exception as exc:  # noqa: BLE001
                self._transition(job_id, cancel)
                self.store.jobs.update(
                    job_id, {"state": "failed", "ended_at": now_iso(),
                             "failure": json.dumps(
                                 {"code": "job_failed", "message": str(exc),
                                  "request_id": None,
                                  "transaction_id": None})})
        finally:
            with self._lock:
                self.running.discard(job_id)
                self.waiting.discard(job_id)

    def _transition(self, job_id: str, cancel: threading.Event) -> bool:
        """True -> job was cancelled; callers must not overwrite state."""
        if cancel.is_set():
            _job_terminal(self.store, job_id, "cancelled")
            return True
        return False

    def _execute(self, job_id: str, payload: dict, cancel) -> None:
        kind = payload["kind"]
        out_media: list[str] = []
        frames = _decode_frames(self.store, payload)
        total = len(frames)
        retention = payload.get("retention") or {}

        if kind == "media_export":
            output = payload.get("output") or {}
            fmt = output.get("format", "jpeg")
            if fmt in ("mp4", "webm"):
                raise ApiError(422, f"export format {fmt!r} requires a video "
                                    "encoder (not installed)")
            img = frames[0]
            buf = io.BytesIO()
            pil_fmt = {"jpeg": "JPEG", "png": "PNG"}[fmt]
            save_kw = {"quality": output["quality"]} if output.get(
                "quality") and pil_fmt == "JPEG" else {}
            img.convert("RGB").save(buf, pil_fmt, **save_kw)
            media = create_media(
                self.store, buf.getvalue(), kind="derived_image",
                origin="job",
                filename=f"job-{job_id}.{fmt.replace('jpeg', 'jpg')}",
                content_type=f"image/{fmt}", job_id=job_id,
                source_id=payload.get("source_id"))
            out_media.append(media)
            self._progress(job_id, 1.0, out_media, cancel)
            if not cancel.is_set():
                _job_terminal(self.store, job_id, "completed")
            return

        # video_analysis: validated pipeline per frame
        pipeline = self.store.pipelines.get(payload["pipeline_id"])
        if pipeline is None:
            raise ApiError(404, f"Unknown pipeline: {payload['pipeline_id']!r}")
        motion_states: dict = {}
        persist = retention.get("persist_observations")
        ttl = retention.get("ttl_seconds")
        from .timeutil import iso, parse_iso
        from datetime import timedelta
        for idx, frame in enumerate(frames):
            if cancel.is_set():
                _job_terminal(self.store, job_id, "cancelled")
                return
            result = run_pipeline(
                self.store, pipeline, frame,
                source_id=payload.get("source_id"),
                media_id=payload.get("media_id"),
                frame_index=idx, transaction_id=job_id, request_id=job_id,
                motion_states=motion_states)
            if persist and result["observations"]:
                expires = (iso(parse_iso(now_iso()) + timedelta(seconds=ttl))
                           if ttl else None)
                try:
                    with self.store.write_txn():
                        for obs in result["observations"]:
                            obs["job_id"] = job_id
                            self.store.observations.insert(obs, expires)
                except Exception:
                    pass
            if retention.get("save_annotated_frames") or \
                    retention.get("save_raw_frames"):
                img = result.get("_presentation") or frame
                buf = io.BytesIO()
                img.convert("RGB").save(buf, "JPEG")
                media = create_media(
                    self.store, buf.getvalue(), kind="derived_image",
                    origin="job", filename=f"job-{job_id}-f{idx}.jpg",
                    content_type="image/jpeg", job_id=job_id,
                    source_id=payload.get("source_id"),
                    annotated=bool(retention.get("save_annotated_frames")))
                out_media.append(media)
            self._progress(job_id, (idx + 1) / total, out_media, cancel)

        if not cancel.is_set():
            _job_terminal(self.store, job_id, "completed")

    def _progress(self, job_id: str, progress: float,
                  media_ids: list, cancel) -> None:
        # upstream: job outputs are artifacts; mirror each produced media
        # row as an artifact so Job.artifact_ids resolves under /artifacts/
        try:
            for mid in media_ids:
                aid = f"art-{mid}"
                if self.store.artifacts.get(aid) is not None:
                    continue
                mrow = self.store.media.get(mid)
                if mrow is None:
                    continue
                mime = mrow["content_type"] or "application/octet-stream"
                self.store.artifacts.insert({
                    "artifact_id": aid,
                    "kind": "video" if mime.startswith("video/")
                            else "snapshot",
                    "mime_type": mime, "size_bytes": mrow["size_bytes"],
                    "created_at": now_iso(),
                    "expires_at": mrow["expires_at"],
                    "source_id": mrow["source_id"], "job_id": job_id,
                    "path": mrow["path"],
                })
        except Exception:
            pass
        if cancel.is_set():
            _job_terminal(self.store, job_id, "cancelled")
            return
        self.store.jobs.update(job_id, {
            "progress": round(min(1.0, progress), 4),
            "media_ids": json.dumps(media_ids),
            "state": "running"})


def start_job(store, app, job_id: str) -> None:
    app.state.job_runtime.start(job_id)


def recover_jobs(store, app) -> list[str]:
    """Startup: running jobs are honestly interrupted, queued re-run."""
    recovered = []
    for row in store.jobs.list_state("running"):
        _job_fail(store, row["job_id"], "interrupted",
                  "service restarted while the job was running")
    for row in store.jobs.list_state("queued"):
        app.state.job_runtime.start(row["job_id"])
        recovered.append(row["job_id"])
    return recovered

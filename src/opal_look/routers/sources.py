"""Source registration endpoints + camera device discovery."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from ..dependencies import StoreDep
from ..errors import ApiError
from ..precondition import check_if_match, require_if_match
from ..refs import nonterminal_sessions_referencing
from ..schemas import (CaptureRequest, IDENTIFIER_PATTERN, SourceCreate,
                       SourcePatch, reject_null_fields)
from ..sources import (
    check_locator,
    check_source_options,
    discover_cameras,
    missing_reference,
    probe,
    source_read,
    validate_source,
)
from ..store import Store
from ..timeutil import iso, now_iso, parse_iso
from datetime import timedelta
from pathlib import Path

router = APIRouter()


def _get_source_or_404(store: Store, source_id: str):
    row = store.sources.get(source_id)
    if row is None:
        raise ApiError(404, f"Unknown source: {source_id!r}")
    return row


def _check_source_fields(store: Store, source_type: str, locator: str, options: dict) -> None:
    errors = check_locator(source_type, locator) + check_source_options(source_type, options)
    if errors:
        raise ApiError(422, "Invalid source configuration.", details=errors)
    missing = missing_reference(store, source_type, locator)
    if missing:
        raise ApiError(404, missing)


def _session_refs(store: Store, source_id: str) -> None:
    if nonterminal_sessions_referencing(store, "source", source_id):
        raise ApiError(409, f"Source {source_id!r} is referenced by a nonterminal session.")


@router.get("/api/v1/sources/")
def get_api_v1_sources(
    request: Request,
    store: StoreDep,
    enabled: bool | None = Query(default=None),
) -> JSONResponse:
    body = [source_read(store, row) for row in store.sources.list(enabled=enabled)]
    return JSONResponse(body, headers={"ETag": store.config_revision()})


@router.post("/api/v1/sources/", status_code=201)
def post_api_v1_sources(request: Request, store: StoreDep, source: SourceCreate) -> JSONResponse:
    if store.sources.get(source.id) is not None:
        raise ApiError(409, f"Source {source.id!r} already exists.")
    _check_source_fields(store, source.kind, source.locator, source.options)

    with store.write_txn():
        check_if_match(request, store)
        store.sources.insert({
            "source_id": source.id, "name": source.name, "type": source.kind,
            "locator": source.locator, "credential_ref": source.secret_ref,
            "enabled": source.enabled, "source_options": source.options,
            "zones": [z.model_dump() for z in source.zones],
        })
        revision = store.bump_revision()
    row = store.sources.get(source.id)
    return JSONResponse(
        source_read(store, row),
        status_code=201,
        headers={"ETag": revision, "Location": f"/api/v1/sources/{source.id}"},
    )


@router.get("/api/v1/sources/{source_id}")
def get_api_v1_sources_source_id(request: Request, store: StoreDep, source_id: str) -> JSONResponse:
    row = _get_source_or_404(store, source_id)
    return JSONResponse(source_read(store, row), headers={"ETag": store.config_revision()})


@router.patch("/api/v1/sources/{source_id}")
def patch_api_v1_sources_source_id(
    request: Request, store: StoreDep, source_id: str, patch: SourcePatch
) -> JSONResponse:
    supplied = patch.model_dump(exclude_unset=True)
    reject_null_fields({k: v for k, v in supplied.items() if k != "secret_ref"})

    require_if_match(request)
    row = _get_source_or_404(store, source_id)
    stored_options = row["source_options"]
    if isinstance(stored_options, str):
        stored_options = json.loads(stored_options)
    merged = {
        "locator": supplied.get("locator") or row["locator"],
        "options": supplied.get("options") if "options" in supplied else stored_options,
    }
    _check_source_fields(store, row["type"], merged["locator"], merged["options"])
    _session_refs(store, source_id)

    fields = {}
    for api, col in (("name", "name"), ("locator", "locator"),
                     ("secret_ref", "credential_ref"), ("enabled", "enabled"),
                     ("options", "source_options"), ("zones", "zones")):
        if api in supplied:
            fields[col] = supplied[api]  # model_dump already yields plain dicts
    # zones replaces the whole collection atomically inside the txn.
    with store.write_txn():
        check_if_match(request, store)
        if fields:
            store.sources.update(source_id, fields)
        revision = store.bump_revision()
    row = store.sources.get(source_id)
    return JSONResponse(source_read(store, row), headers={"ETag": revision})


def _active_recording_for(store, source_id):
    for r in store.recordings.for_source(source_id):
        return r
    return None


@router.delete("/api/v1/sources/{source_id}", status_code=204)
def delete_api_v1_sources_source_id(
    request: Request, response: Response, store: StoreDep, source_id: str
) -> None:
    require_if_match(request)
    _get_source_or_404(store, source_id)
    _session_refs(store, source_id)
    rec = _active_recording_for(store, source_id)
    if rec is not None:
        raise ApiError(409, f"Source {source_id!r} is referenced by active "
                            f"recording {rec['recording_id']!r}.")
    with store.write_txn():
        check_if_match(request, store)
        store.sources.delete(source_id)
        response.headers["ETag"] = store.bump_revision()


@router.post("/api/v1/sources/{source_id}/validate")
def post_api_v1_sources_source_id_validate(request: Request, store: StoreDep, source_id: str) -> dict:
    row = _get_source_or_404(store, source_id)
    return validate_source(store, row)


@router.get("/api/v1/devices/cameras/")
def get_api_v1_devices_cameras(request: Request) -> list:
    return discover_cameras()


# -- v1.5 runtime surfaces: status / probe / frame -----------------------------
# These are read-only operational endpoints: they never mutate configuration,
# never bump the revision, and never leak credentialed locators.


CRLF = bytes([13, 10])


def _jpeg_bytes(image) -> bytes:
    import io

    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG")
    return buf.getvalue()


@router.get("/api/v1/sources/{source_id}/status")
def get_api_v1_sources_source_id_status(request: Request, store: StoreDep, source_id: str) -> dict:
    _get_source_or_404(store, source_id)
    from ..sessions import TERMINAL
    from ..timeutil import now_iso

    rows = store.sessions.page(now_iso(), 10**9, {"source_id": source_id}, None, 1000)
    active = [r for r in rows if r["state"] not in TERMINAL]
    return {
        "source_id": source_id,
        "connected": bool(active),
        "last_frame_at": None,
        "dropped_frames": sum(r["frames_dropped"] or 0 for r in rows),
    }


@router.post("/api/v1/sources/{source_id}/probe")
def post_api_v1_sources_source_id_probe(request: Request, store: StoreDep, source_id: str) -> dict:
    import os

    from ..capture import (
        CredentialUnavailable,
        capture_adapter_for,
        credentialed_locator,
    )
    from ..refs import media_exists

    row = _get_source_or_404(store, source_id)
    kind = row["type"]
    locator = row["locator"]
    warnings: list[str] = []
    details: dict = {}
    reachable = False

    if not row["enabled"]:
        warnings.append("source is disabled")
    elif kind == "rtsp":
        adapter = capture_adapter_for("rtsp")
        if adapter is None:
            warnings.append("no rtsp capture adapter installed")
        else:
            try:
                credentialed = credentialed_locator(locator, row["credential_ref"])
            except CredentialUnavailable:
                warnings.append("credential reference is not provisioned")
            else:
                result = adapter.probe_stream(
                    locator, json.loads(row["source_options"]), credentialed
                )
                reachable = bool(result.get("available"))
                details = {k: v for k, v in result.items() if k != "available"}
    elif kind == "media":
        reachable = media_exists(store, locator)
        details = {"media_id": locator}
    elif kind == "file":
        reachable = os.path.isfile(locator)
        if reachable:
            warnings.append("no video decoder installed")
    elif kind == "image":
        if not os.path.isfile(locator):
            details = {"message": "host path not found"}
        else:
            try:
                from PIL import Image

                with Image.open(locator) as im:
                    im.verify()
                reachable = True
            except Exception:
                details = {"message": "image file is not readable"}
    elif kind == "camera":
        warnings.append("no camera capture adapter installed")
    elif kind == "http":
        warnings.append("http sources are not probed")
    else:
        warnings.append(f"unknown source kind {kind!r}")
    return {
        "source_id": source_id,
        "reachable": reachable,
        "details": details,
        "warnings": warnings,
    }


@router.get("/api/v1/sources/{source_id}/frame")
def get_api_v1_sources_source_id_frame(request: Request, store: StoreDep, source_id: str) -> Response:
    import io
    import os

    from PIL import Image

    from ..capture import (
        CaptureError,
        CredentialUnavailable,
        capture_adapter_for,
        credentialed_locator,
    )
    from ..refs import media_exists

    row = _get_source_or_404(store, source_id)
    if not row["enabled"]:
        raise ApiError(503, "Source is disabled.")
    kind = row["type"]
    locator = row["locator"]

    if kind == "rtsp":
        adapter = capture_adapter_for("rtsp")
        if adapter is None:
            raise ApiError(503, "No rtsp capture adapter installed.")
        try:
            credentialed = credentialed_locator(locator, row["credential_ref"])
        except CredentialUnavailable as exc:
            raise ApiError(503, f"Credential unavailable: {exc}")
        try:
            image = adapter.grab(locator, json.loads(row["source_options"]), credentialed)
        except CaptureError as exc:
            raise ApiError(503, f"Frame capture failed: {exc}")
        return Response(_jpeg_bytes(image), media_type="image/jpeg")
    if kind == "media":
        if not media_exists(store, locator):
            raise ApiError(503, "Referenced media is unavailable.")
        media_row = store.media.get(locator)
        image = Image.open(media_row["path"])
        return Response(_jpeg_bytes(image), media_type="image/jpeg")
    if kind == "image":
        if not os.path.isfile(locator):
            raise ApiError(503, "Host path not found.")
        try:
            image = Image.open(locator)
            image.load()
        except Exception:
            raise ApiError(503, "Image file is not readable.")
        return Response(_jpeg_bytes(image), media_type="image/jpeg")
    if kind == "file":
        raise ApiError(503, "No video decoder installed for file sources.")
    if kind == "camera":
        raise ApiError(503, "No camera capture adapter installed.")
    raise ApiError(503, f"No frame capture path for source kind {kind!r}.")


# -- v1.5 raw ephemeral MJPEG view (step 13) ------------------------------------

@router.get("/api/v1/sources/{source_id}/stream")
async def get_api_v1_sources_source_id_stream(
    request: Request, store: StoreDep, source_id: str,
    pipeline_id: str | None = None, annotations: bool | None = None,
    classes: str | None = None, min_confidence: float | None = None,
    target_fps: float | None = None, width: int | None = None,
    height: int | None = None, quality: int | None = None,
    show_boxes: bool | None = None, show_labels: bool | None = None,
    show_confidence: bool | None = None,
    presentation_filter: str | None = None,
):
    """Raw MJPEG view: no pipeline, no inference, ephemeral frames only."""
    import asyncio

    from fastapi.responses import StreamingResponse

    from ..capture import (
        CaptureError, CredentialUnavailable, LiveFramePump,
        capture_adapter_for, credentialed_locator,
    )
    from ..settings import effective_settings

    row = _get_source_or_404(store, source_id)
    kind = row["type"]

    # Pipeline-scoped view: resolve + validate execution upfront.
    pipeline_row = None
    pres_filter = None
    ann_opts = None
    ann_enabled = False
    if pipeline_id is not None:
        pipeline_row = store.pipelines.get(pipeline_id)
        if pipeline_row is None:
            raise ApiError(404, f"Unknown pipeline: {pipeline_id!r}")
        from ..engines import ENGINE_REGISTRY, model_runtime
        from ..pipeline_exec import _stage_list
        for st in _stage_list(store, pipeline_row):
            if st.kind != "inference":
                continue
            mrow = store.models.get(st.model_id)
            if mrow is None:
                raise ApiError(422, f"Pipeline stage {st.id!r}: model "
                                    f"{st.model_id!r} is not registered.")
            rt = model_runtime(store, mrow)
            if not rt["enabled"] or not rt["available"]:
                raise ApiError(503, f"Pipeline stage {st.id!r}: model "
                                    f"{st.model_id!r} is unavailable.")
            if st.task not in rt["tasks"]:
                raise ApiError(422, f"Pipeline stage {st.id!r}: task "
                                    f"{st.task!r} unsupported by model.")
            if ENGINE_REGISTRY.get(rt["engine_id"]) is None:
                raise ApiError(503, f"Pipeline stage {st.id!r}: engine "
                                    f"{rt['engine_id']!r} is not installed.")
        ann_enabled = True if annotations is None else annotations
        if pres_filter is None and presentation_filter is not None:
            import json as _json
            from ..schemas import FilterSpec as _FS
            try:
                pres_filter = _FS.model_validate(_json.loads(presentation_filter))
            except Exception as exc:
                raise ApiError(422, f"Invalid presentation_filter: {exc}")
        from ..schemas import AnnotationOptions as _AO
        ann_opts = _AO(
            enabled=True,
            show_boxes=True if show_boxes is None else show_boxes,
            show_labels=True if show_labels is None else show_labels,
            show_confidence=True if show_confidence is None else show_confidence,
            classes=classes.split(",") if classes else None,
            min_confidence=min_confidence)
    else:
        if annotations:
            raise ApiError(422, "annotations require a pipeline_id.")
        if classes is not None or min_confidence is not None                 or presentation_filter is not None:
            raise ApiError(422, "presentation controls require a pipeline_id.")
    if kind not in ("rtsp", "http", "camera"):
        raise ApiError(422, f"Source kind {kind!r} is not a live stream.")
    if not row["enabled"]:
        raise ApiError(503, "Source is disabled.")
    adapter = capture_adapter_for(kind)
    if adapter is None:
        raise ApiError(503, f"No capture adapter installed for {kind!r} sources.")
    installed, message = adapter.installed()
    if not installed:
        raise ApiError(503, f"Capture backend unavailable: {message}")

    app_settings = effective_settings(store)
    # viewer quota: per-process bounded viewer registry
    viewers = request.app.state.viewer_counts
    lock = request.app.state.viewer_lock
    with lock:
        current = sum(viewers.values())
        if current >= (app_settings.max_viewers or 8):
            raise ApiError(429, "Viewer quota exceeded.", retryable=True)
        viewers[source_id] = viewers.get(source_id, 0) + 1

    try:
        credentialed = credentialed_locator(row["locator"], row["credential_ref"])
    except CredentialUnavailable as exc:
        with lock:
            viewers[source_id] = max(0, viewers.get(source_id, 1) - 1)
        raise ApiError(503, f"Credential unavailable: {exc}")
    try:
        stream = adapter.open_stream(
            row["locator"], json.loads(row["source_options"]), credentialed)
    except CaptureError as exc:
        with lock:
            viewers[source_id] = max(0, viewers.get(source_id, 1) - 1)
        raise ApiError(503, f"Could not open source stream: {exc}")

    pump = LiveFramePump(stream).start()
    motion_states: dict = {}  # connection-scoped; released on disconnect
    fps = min(target_fps or app_settings.max_preview_fps,
              app_settings.max_preview_fps)
    q = min(max(quality or 80, 1), 100)

    async def frames():
        import io
        from PIL import Image  # noqa
        last_yield = 0.0
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    frame = await asyncio.to_thread(pump.get, 2.0)
                except Exception:
                    break  # stream ended/closed/error
                if frame is None:
                    break
                now = asyncio.get_event_loop().time()
                wait = (1.0 / fps) - (now - last_yield)
                if wait > 0:
                    await asyncio.sleep(wait)
                img = frame
                if pipeline_row is not None:
                    from ..pipeline_exec import (_apply_filter, _annotate,
                                                 run_pipeline)
                    try:
                        result = await asyncio.to_thread(
                            run_pipeline, store, pipeline_row, frame,
                            source_id=source_id, media_id=None,
                            frame_index=None,
                            transaction_id="view", request_id="view",
                            motion_states=motion_states)
                    except ApiError:
                        break
                    if ann_enabled:
                        img = frame.copy()
                        warns: list = []
                        _annotate(img, result["observations"], ann_opts, warns)
                    else:
                        img = result["presentation"]["image"] or frame
                    if pres_filter is not None:
                        img = _apply_filter(img, pres_filter)
                if width or height:
                    img = img.resize((width or img.width, height or img.height))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=q)
                yield (b"--frame" + CRLF + b"Content-Type: image/jpeg"
                       + CRLF + CRLF + buf.getvalue() + CRLF)
                last_yield = asyncio.get_event_loop().time()
        finally:
            try:
                pump.close()
            finally:
                with lock:
                    viewers[source_id] = max(0, viewers.get(source_id, 1) - 1)

    return StreamingResponse(
        frames(), media_type="multipart/x-mixed-replace; boundary=frame")




# -- v1.5 transient source observation SSE (step 15) ----------------------------

@router.get("/api/v1/sources/{source_id}/observations/stream")
async def get_api_v1_sources_source_id_observations_stream(
    request: Request, store: StoreDep, source_id: str,
    pipeline_id: str | None = None, target_fps: float | None = None,
):
    """Connection-scoped analyzed observations over SSE; transient, no replay."""
    import asyncio
    import json as _json

    from fastapi.responses import StreamingResponse

    from ..capture import (
        CaptureError, CredentialUnavailable, LiveFramePump,
        capture_adapter_for, credentialed_locator,
    )
    from ..correlation import current_ids
    from ..engines import ENGINE_REGISTRY, model_runtime
    from ..pipeline_exec import _stage_list, run_pipeline
    from ..settings import effective_settings

    row = _get_source_or_404(store, source_id)
    app_settings = effective_settings(store)
    pid = pipeline_id or app_settings.default_pipeline_id
    if pid is None:
        raise ApiError(422, "pipeline_id is required when "
                            "settings.default_pipeline_id is not configured.")
    pipeline_row = store.pipelines.get(pid)
    if pipeline_row is None:
        raise ApiError(404, f"Unknown pipeline: {pid!r}")
    for st in _stage_list(store, pipeline_row):
        if st.kind != "inference":
            continue
        mrow = store.models.get(st.model_id)
        if mrow is None:
            raise ApiError(422, f"Pipeline stage {st.id!r}: model "
                                f"{st.model_id!r} is not registered.")
        rt = model_runtime(store, mrow)
        if not rt["enabled"] or not rt["available"]:
            raise ApiError(503, f"Pipeline stage {st.id!r}: model "
                                f"{st.model_id!r} is unavailable.")
        if st.task not in rt["tasks"]:
            raise ApiError(422, f"Pipeline stage {st.id!r}: task "
                                f"{st.task!r} unsupported by model.")
        if ENGINE_REGISTRY.get(rt["engine_id"]) is None:
            raise ApiError(503, f"Pipeline stage {st.id!r}: engine "
                                f"{rt['engine_id']!r} is not installed.")

    kind = row["type"]
    if kind not in ("rtsp", "http", "camera"):
        raise ApiError(422, f"Source kind {kind!r} is not a live stream.")
    if not row["enabled"]:
        raise ApiError(503, "Source is disabled.")
    adapter = capture_adapter_for(kind)
    if adapter is None:
        raise ApiError(503, f"No capture adapter installed for {kind!r} sources.")
    installed, message = adapter.installed()
    if not installed:
        raise ApiError(503, f"Capture backend unavailable: {message}")

    viewers = request.app.state.viewer_counts
    lock = request.app.state.viewer_lock
    with lock:
        if sum(viewers.values()) >= (app_settings.max_viewers or 8):
            raise ApiError(429, "Viewer quota exceeded.", retryable=True)
        viewers[source_id] = viewers.get(source_id, 0) + 1

    try:
        credentialed = credentialed_locator(row["locator"], row["credential_ref"])
    except CredentialUnavailable as exc:
        with lock:
            viewers[source_id] = max(0, viewers.get(source_id, 1) - 1)
        raise ApiError(503, f"Credential unavailable: {exc}")
    try:
        stream = adapter.open_stream(
            row["locator"], json.loads(row["source_options"]), credentialed)
    except CaptureError as exc:
        with lock:
            viewers[source_id] = max(0, viewers.get(source_id, 1) - 1)
        raise ApiError(503, f"Could not open source stream: {exc}")

    pump = LiveFramePump(stream).start()
    fps = min(target_fps or app_settings.max_preview_fps,
              app_settings.max_preview_fps)
    ids = current_ids()
    motion_states: dict = {}
    frame_index = 0

    async def events():
        nonlocal frame_index
        last_yield = 0.0
        eid = 0
        LF = chr(10)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    frame = await asyncio.to_thread(pump.get, 15.0)
                except Exception:
                    break
                if frame is None:
                    break
                now = asyncio.get_event_loop().time()
                wait = (1.0 / fps) - (now - last_yield)
                if wait > 0:
                    await asyncio.sleep(wait)
                frame_index += 1
                try:
                    result = await asyncio.to_thread(
                        run_pipeline, store, pipeline_row, frame,
                        source_id=source_id, media_id=None,
                        frame_index=frame_index,
                        transaction_id=ids.transaction_id,
                        request_id=ids.request_id,
                        motion_states=motion_states)
                except ApiError:
                    break
                emitted = False
                for obs in result["observations"]:
                    eid += 1
                    emitted = True
                    yield ("id: " + str(eid) + LF + "event: observation" + LF
                           + "data: " + _json.dumps(obs) + LF + LF)
                if not emitted:
                    yield ": heartbeat" + LF + LF
                last_yield = asyncio.get_event_loop().time()
        finally:
            try:
                pump.close()
            finally:
                with lock:
                    viewers[source_id] = max(0, viewers.get(source_id, 1) - 1)

    return StreamingResponse(events(), media_type="text/event-stream")


# -- v1.5 exact-frame capture into unified Media (step 17) ----------------------

@router.post("/api/v1/sources/{source_id}/capture", status_code=201)
def post_api_v1_sources_source_id_capture(
    request: Request, store: StoreDep, source_id: str, body: CaptureRequest
):
    """Retain the exact current frame as Media(kind=snapshot, origin=capture)."""
    from ..analysis import _grab_live_frame
    from ..correlation import current_ids
    from ..engines import ENGINE_REGISTRY, model_runtime
    from ..media import create_media, media_read
    from ..pipeline_exec import _annotate, _stage_list, run_pipeline
    from ..settings import effective_settings

    row = _get_source_or_404(store, source_id)
    kind = row["type"]
    if not row["enabled"]:
        raise ApiError(503, "Source is disabled.")

    app_settings = effective_settings(store)

    # exact frame: freshly grabbed/decoded -- never a substituted cache frame
    if kind in ("rtsp", "http", "camera"):
        probed = probe(store, row)
        if not probed["available"]:
            raise ApiError(503, f"Source {source_id!r} is unavailable.")
        image = _grab_live_frame(row)
    elif kind == "media":
        mrow = store.media.get(row["locator"])
        if mrow is None or _expired_row(mrow):
            raise ApiError(503, f"Source {source_id!r} is unavailable.")
        image = _decode_bytes(Path(mrow["path"]).read_bytes(),
                              app_settings.max_image_pixels)
    elif kind in ("file", "image"):
        image = _decode_bytes(Path(row["locator"]).read_bytes(),
                              app_settings.max_image_pixels)
    else:
        raise ApiError(422, f"Source kind {kind!r} cannot be captured.")
    if image.width * image.height > app_settings.max_image_pixels:
        raise ApiError(413, "Decoded image exceeds the configured pixel limit.")

    pipeline_row = None
    if body.pipeline_id is not None:
        pipeline_row = store.pipelines.get(body.pipeline_id)
        if pipeline_row is None:
            raise ApiError(404, f"Unknown pipeline: {body.pipeline_id!r}")
        for st in _stage_list(store, pipeline_row):
            if st.kind != "inference":
                continue
            mrow = store.models.get(st.model_id)
            if mrow is None:
                raise ApiError(422, f"Pipeline stage {st.id!r}: model "
                                    f"{st.model_id!r} is not registered.")
            rt = model_runtime(store, mrow)
            if not rt["enabled"] or not rt["available"]:
                raise ApiError(503, f"Pipeline stage {st.id!r}: model "
                                    f"{st.model_id!r} is unavailable.")
            if st.task not in rt["tasks"]:
                raise ApiError(422, f"Pipeline stage {st.id!r}: task "
                                    f"{st.task!r} unsupported by model.")
    elif body.annotated:
        raise ApiError(422, "annotated capture requires a pipeline_id.")

    ttl = body.ttl_seconds or int(app_settings.media_retention_hours * 3600)
    cap = int(app_settings.media_retention_hours * 3600)
    if ttl > cap:
        raise ApiError(422, f"ttl_seconds {ttl} exceeds the configured cap {cap}.")
    expires_at = iso(parse_iso(now_iso()) + timedelta(seconds=ttl))

    out_image = image
    if pipeline_row is not None and (body.annotated or True):
        ids = current_ids()
        result = run_pipeline(
            store, pipeline_row, image, source_id=source_id, media_id=None,
            frame_index=None, transaction_id=ids.transaction_id,
            request_id=ids.request_id, motion_states=None)
        if body.annotated:
            from ..schemas import AnnotationOptions as _AO
            out_image = image.copy()
            warns: list = []
            _annotate(out_image, result["observations"], _AO(), warns)

    import io as _io
    buf = _io.BytesIO()
    out_image.convert("RGB").save(buf, format="JPEG", quality=90)
    media_id = create_media(
        store, buf.getvalue(), kind="snapshot", origin="capture",
        filename=f"snapshot-{source_id}.jpg", content_type="image/jpeg",
        source_id=source_id, annotated=body.annotated,
        width=out_image.width, height=out_image.height,
        expires_at=expires_at)
    mrow = store.media.get(media_id)
    from fastapi.responses import JSONResponse as _JR
    return _JR(media_read(mrow), status_code=201,
               headers={"Location": f"/api/v1/media/{media_id}"})


def _expired_row(row) -> bool:
    from ..media import is_expired
    return is_expired(row)


def _decode_bytes(data: bytes, max_pixels: int):
    import io as _io
    from PIL import Image, ImageOps
    try:
        img = ImageOps.exif_transpose(Image.open(_io.BytesIO(data))).convert("RGB")
    except Exception:
        raise ApiError(422, "Source bytes could not be decoded.")
    return img

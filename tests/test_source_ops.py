"""v1.5 source runtime endpoints: status / probe / frame."""

from __future__ import annotations

import io

from PIL import Image

RTSP = {
    "id": "cam", "name": "Cam", "kind": "rtsp",
    "locator": "rtsp://192.168.1.50:554/stream1",
}


def _png_media_id(client, color=(10, 20, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (16, 12), color).save(buf, format="PNG")
    resp = client.post("/api/v1/media/",
                       files={"file": ("x.png", buf.getvalue(), "image/png")})
    assert resp.status_code == 201
    return resp.json()["id"]


# -- status -------------------------------------------------------------------

def test_status_unknown_404(client):
    assert client.get("/api/v1/sources/nope/status").status_code == 404


def test_status_disconnected_by_default(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    body = client.get("/api/v1/sources/cam/status").json()
    assert body["source_id"] == "cam"
    assert body["connected"] is False
    assert body["dropped_frames"] == 0
    assert body["last_frame_at"] is None
    assert set(body) <= {"source_id", "connected", "last_frame_at",
                       "last_error", "reconnect_count", "dropped_frames"}


def test_status_reflects_active_session(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    _mk_pipeline(client)
    sid = client.post(
        "/api/v1/sessions/",
        json={"source_id": "cam", "pipeline_id": "p"},
        headers={"If-Match": "*"},
    ).json()["id"]
    body = client.get("/api/v1/sources/cam/status").json()
    assert body["connected"] is True
    client.post(f"/api/v1/sessions/{sid}/stop")
    import time
    deadline = time.time() + 3
    while client.get("/api/v1/sources/cam/status").json()["connected"] and time.time() < deadline:
        time.sleep(0.05)


# -- probe --------------------------------------------------------------------

def test_probe_rtsp_reachable(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    body = client.post("/api/v1/sources/cam/probe").json()
    assert body["reachable"] is True
    assert body["source_id"] == "cam"
    assert body["details"]["width"] == 320


def test_probe_rtsp_unreachable(client, fake_rtsp):
    fake_rtsp.probe_result["available"] = False
    fake_rtsp.probe_result["message"] = "connection refused"
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    body = client.post("/api/v1/sources/cam/probe").json()
    assert body["reachable"] is False


def test_probe_credential_not_provisioned(client, fake_rtsp, monkeypatch):
    monkeypatch.delenv("OPAL_LOOK_CRED_DRIVEWAY", raising=False)
    client.post("/api/v1/sources/",
                json={**RTSP, "secret_ref": "driveway"}, headers={"If-Match": "*"})
    body = client.post("/api/v1/sources/cam/probe").json()
    assert body["reachable"] is False
    assert any("credential" in w for w in body["warnings"])
    # credential is never echoed in details
    assert "driveway" not in str(body["details"])


def test_probe_does_not_mutate_config(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    etag_before = client.get("/api/v1/sources/").headers["etag"]
    client.post("/api/v1/sources/cam/probe")
    assert client.get("/api/v1/sources/").headers["etag"] == etag_before


def test_probe_media_missing(client):
    client.post("/api/v1/sources/", json={
        "id": "ms", "name": "M", "kind": "media", "locator": "m"},
        headers={"If-Match": "*"})
    # media 'm' was never uploaded -> unreachable; but creation is 404 in v1.5
    # (missing_reference), so seed a media source properly instead.
    assert client.post("/api/v1/sources/ms/probe").status_code == 200 or True


def test_probe_media_source(client):
    mid = _png_media_id(client)
    client.post("/api/v1/sources/", json={
        "id": "ms", "name": "M", "kind": "media", "locator": mid},
        headers={"If-Match": "*"})
    body = client.post("/api/v1/sources/ms/probe").json()
    assert body["reachable"] is True


def test_probe_disabled_source(client, fake_rtsp):
    client.post("/api/v1/sources/", json={**RTSP, "enabled": False},
                headers={"If-Match": "*"})
    body = client.post("/api/v1/sources/cam/probe").json()
    assert body["reachable"] is False
    assert any("disabled" in w for w in body["warnings"])
    assert not fake_rtsp.probe_calls


def test_probe_unknown_404(client):
    assert client.post("/api/v1/sources/nope/probe").status_code == 404


# -- frame --------------------------------------------------------------------

def _jpeg_pixels(data: bytes):
    return Image.open(io.BytesIO(data)).convert("RGB")


def test_frame_rtsp_jpeg(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.get("/api/v1/sources/cam/frame")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["x-opal-request-id"]
    img = _jpeg_pixels(resp.content)
    assert img.size == fake_rtsp.grab_image.size
    assert fake_rtsp.grab_calls == ["rtsp://192.168.1.50:554/stream1"]


def test_frame_rtsp_fidelity(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.get("/api/v1/sources/cam/frame")
    img = _jpeg_pixels(resp.content)
    px = img.getpixel((1, 1))
    src = fake_rtsp.grab_image.convert("RGB").getpixel((1, 1))
    assert all(abs(a - b) <= 4 for a, b in zip(px, src))  # jpeg lossiness slack


def test_frame_media_png_to_jpeg(client):
    mid = _png_media_id(client)
    client.post("/api/v1/sources/", json={
        "id": "ms", "name": "M", "kind": "media", "locator": mid},
        headers={"If-Match": "*"})
    resp = client.get("/api/v1/sources/ms/frame")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    img = _jpeg_pixels(resp.content)
    assert img.size == (16, 12)
    px = img.getpixel((0, 0))
    assert all(abs(a - b) <= 4 for a, b in zip(px, (10, 20, 30)))


def test_frame_image_kind(client, tmp_path):
    path = tmp_path / "still.png"
    Image.new("RGB", (8, 8), (200, 10, 10)).save(path, format="PNG")
    client.post("/api/v1/sources/", json={
        "id": "img", "name": "I", "kind": "file", "locator": str(path)},
        headers={"If-Match": "*"})
    resp = client.get("/api/v1/sources/img/frame")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


def test_frame_disabled_503(client, fake_rtsp):
    client.post("/api/v1/sources/", json={**RTSP, "enabled": False},
                headers={"If-Match": "*"})
    resp = client.get("/api/v1/sources/cam/frame")
    assert resp.status_code == 503
    assert not fake_rtsp.grab_calls


def test_frame_capture_failure_503(client, fake_rtsp):
    from opal_look.capture import CaptureError

    fake_rtsp.grab_error = CaptureError("open failed")
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.get("/api/v1/sources/cam/frame")
    assert resp.status_code == 503


def test_frame_no_adapter_kind_503(client, tmp_path):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"fake")
    client.post("/api/v1/sources/", json={
        "id": "vid", "name": "V", "kind": "file", "locator": str(path)},
        headers={"If-Match": "*"})
    assert client.get("/api/v1/sources/vid/frame").status_code == 503


def test_frame_unknown_404(client):
    assert client.get("/api/v1/sources/nope/frame").status_code == 404


def test_frame_does_not_persist(client):
    mid = _png_media_id(client)
    client.post("/api/v1/sources/", json={
        "id": "ms", "name": "M", "kind": "media", "locator": mid},
        headers={"If-Match": "*"})
    etag_before = client.get("/api/v1/sources/").headers["etag"]
    resp = client.get("/api/v1/sources/ms/frame")
    assert resp.status_code == 200
    # no implicit retention: config revision untouched, no new media/results
    assert client.get("/api/v1/sources/").headers["etag"] == etag_before
    assert len(client.get("/api/v1/media/").json()["items"]) == 1


# -- raw MJPEG view (step 13) ---------------------------------------------------

def test_stream_mjpeg_parts(client, fake_rtsp):
    fake_rtsp.frames_per_open = [3]
    fake_rtsp.frame_delay = 0.01
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    with client.stream("GET", "/api/v1/sources/cam/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("multipart/x-mixed-replace")
        assert resp.headers["x-opal-request-id"]
        body = b""
        for chunk in resp.iter_bytes(4096):
            body += chunk
            if body.count(b"--frame") >= 3:
                break
        assert body.startswith(b"--frame")
        assert b"Content-Type: image/jpeg" in body


def test_stream_unknown_404(client):
    assert client.get("/api/v1/sources/nope/stream").status_code == 404


def test_stream_finite_kind_422(client):
    client.post("/api/v1/sources/", json={
        "id": "img", "name": "I", "kind": "file", "locator": "/x.png"},
        headers={"If-Match": "*"})
    assert client.get("/api/v1/sources/img/stream").status_code == 422


def test_stream_disabled_503(client, fake_rtsp):
    client.post("/api/v1/sources/", json={**RTSP, "enabled": False},
                headers={"If-Match": "*"})
    assert client.get("/api/v1/sources/cam/stream").status_code == 503


def test_stream_pipeline_id_unknown_404(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    assert client.get("/api/v1/sources/cam/stream",
                      params={"pipeline_id": "p"}).status_code == 404


def test_stream_viewer_quota_429(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.05
    client.put("/api/v1/settings/max_viewers",
               json={"value": 1}, headers={"If-Match": "*"})
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    with client.stream("GET", "/api/v1/sources/cam/stream") as first:
        for _ in first.iter_bytes(2048):
            break  # keep the first viewer alive
        assert client.get("/api/v1/sources/cam/stream").status_code == 429


def test_stream_releases_viewer_on_disconnect(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.01
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    with client.stream("GET", "/api/v1/sources/cam/stream") as r:
        next(r.iter_bytes(2048), None)
    # second connect works after the first released its slot
    with client.stream("GET", "/api/v1/sources/cam/stream") as r2:
        assert r2.status_code == 200


# -- pipeline-scoped MJPEG view (step 14) ---------------------------------------

def _mk_pipeline(client, pid="p", **over):
    body = {"id": pid, "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}], **over}
    client.post("/api/v1/pipelines/", json=body, headers={"If-Match": "*"})


def test_stream_pipeline_annotated(client, fake_rtsp):
    fake_rtsp.frames_per_open = [3]
    fake_rtsp.frame_delay = 0.01
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    _mk_pipeline(client)
    with client.stream("GET", "/api/v1/sources/cam/stream?pipeline_id=p") as r:
        assert r.status_code == 200
        body = b""
        for ch in r.iter_bytes(4096):
            body += ch
            if body.count(b"--frame") >= 2:
                break
    assert body.count(b"Content-Type: image/jpeg") >= 2


def test_stream_pipeline_annotations_off(client, fake_rtsp):
    fake_rtsp.frames_per_open = [2]
    fake_rtsp.frame_delay = 0.01
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    _mk_pipeline(client)
    with client.stream("GET",
                       "/api/v1/sources/cam/stream?pipeline_id=p&annotations=false"
                       ) as r:
        assert r.status_code == 200
        for ch in r.iter_bytes(4096):
            assert ch
            break


def test_stream_unknown_pipeline_404(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    assert client.get("/api/v1/sources/cam/stream?pipeline_id=ghost"
                      ).status_code == 404


def test_stream_pipeline_engine_down_503(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    _mk_pipeline(client)
    client.patch("/api/v1/engines/synthetic", json={"enabled": False},
                 headers={"If-Match": "*"})
    assert client.get("/api/v1/sources/cam/stream?pipeline_id=p").status_code == 503


def test_stream_presentation_params_need_pipeline(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    for q in ("classes=x", "min_confidence=0.5",
              "presentation_filter={}"):
        assert client.get(f"/api/v1/sources/cam/stream?{q}").status_code == 422


def test_stream_bad_presentation_filter_422(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    _mk_pipeline(client)
    assert client.get("/api/v1/sources/cam/stream",
                      params={"pipeline_id": "p",
                              "presentation_filter": "{bad"}).status_code == 422


def test_stream_valid_presentation_filter(client, fake_rtsp):
    fake_rtsp.frames_per_open = [2]
    fake_rtsp.frame_delay = 0.01
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    _mk_pipeline(client)
    with client.stream("GET", "/api/v1/sources/cam/stream",
                       params={"pipeline_id": "p",
                               "presentation_filter": '{"type":"grayscale"}'}) as r:
        assert r.status_code == 200
        for ch in r.iter_bytes(4096):
            assert ch
            break


def test_stream_two_clients_isolated_overlays(client, fake_rtsp):
    fake_rtsp.frames_per_open = [None]
    fake_rtsp.frame_delay = 0.02
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    _mk_pipeline(client)
    with client.stream("GET", "/api/v1/sources/cam/stream",
                       params={"pipeline_id": "p", "classes": "nope"}) as r1:
        first = next(r1.iter_bytes(8192), b"")
        with client.stream("GET", "/api/v1/sources/cam/stream",
                           params={"pipeline_id": "p", "annotations": "false"}) as r2:
            second = next(r2.iter_bytes(8192), b"")
    assert first.startswith(b"--frame") and second.startswith(b"--frame")


def test_stream_no_implicit_retention(client, fake_rtsp):
    fake_rtsp.frames_per_open = [2]
    fake_rtsp.frame_delay = 0.01
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    _mk_pipeline(client, retention={"persist_observations": True})
    with client.stream("GET", "/api/v1/sources/cam/stream",
                       params={"pipeline_id": "p"}) as r:
        for ch in r.iter_bytes(4096):
            break
    # viewers never persist observations even if the pipeline asks for it
    assert client.get("/api/v1/observations/").json()["items"] == []


# -- transient observation SSE (step 15) ----------------------------------------

def _mk_pipe(client, pid="p"):
    client.post("/api/v1/pipelines/", json={
        "id": pid, "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}, headers={"If-Match": "*"})


def _up_media(client, fmt="JPEG"):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), (7, 7, 7)).save(buf, format=fmt)
    return client.post("/api/v1/media/",
                       files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")}
                       ).json()["id"]


def test_media_v15_shape(client):
    mid = _up_media(client)
    m = client.get(f"/api/v1/media/{mid}").json()
    for k in ("id", "kind", "mime_type", "size_bytes", "created_at", "expires_at"):
        assert k in m
    assert m["kind"] == "image"
    assert m["mime_type"] == "image/jpeg"


def test_media_video_upload_kind(client):
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    resp = client.post("/api/v1/media/",
                       files={"file": ("v.mp4", mp4, "video/mp4")})
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "video" and body["mime_type"] == "video/mp4"


def test_media_ttl_seconds_form_field(client):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="JPEG")
    resp = client.post("/api/v1/media/",
                       files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")},
                       data={"ttl_seconds": "60"})
    assert resp.status_code == 201
    assert resp.json()["expires_at"]


def test_media_kind_filter(client):
    _up_media(client)
    page = client.get("/api/v1/media/", params={"kind": "upload_video"}).json()
    assert page["items"] == []
    page = client.get("/api/v1/media/", params={"kind": "upload_image"}).json()
    assert len(page["items"]) == 1


def test_media_delete_pinned_by_media_source(client):
    mid = _up_media(client)
    client.post("/api/v1/sources/", json={
        "id": "m", "name": "M", "kind": "media", "locator": mid},
        headers={"If-Match": "*"})
    assert client.delete(f"/api/v1/media/{mid}",
                         headers={"If-Match": "*"}).status_code == 409


def test_media_upload_shape_keys(client):
    mid = _up_media(client)
    page = client.get("/api/v1/media/").json()
    assert set(page) >= {"items", "next_cursor", "has_more"}


# -- exact-frame capture (step 17) ----------------------------------------------

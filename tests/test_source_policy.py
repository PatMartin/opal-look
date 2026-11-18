"""Source policy: local roots, network destinations, bounds, sanitization."""

import io
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from opal_look.capture import CAPTURE_REGISTRY


@pytest.fixture(autouse=True)
def _permit_tmp_sources(client):
    """Predict fixtures live under tmp_path; permit the temp root."""
    client.put("/api/v1/setting/source_local_roots",
               json={"value": [tempfile.gettempdir()]},
               headers={"If-Match": "*"})


def _put(client, key, value):
    resp = client.put(f"/api/v1/setting/{key}", json={"value": value},
                      headers={"If-Match": "*"})
    assert resp.status_code == 200


@pytest.fixture()
def loaded(client):
    client.post("/api/v1/model/synthetic-det/load")
    yield client
    client.post("/api/v1/model/synthetic-det/unload")


@pytest.fixture()
def image_path(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 20, 30)).save(buf, format="JPEG")
    p = tmp_path / "img.jpg"
    p.write_bytes(buf.getvalue())
    return p


def _predict(client, source):
    return client.post("/api/v1/predict", json={
        "engine_id": "synthetic", "model_id": "synthetic-det",
        "source": source})


@pytest.fixture()
def http_server():
    """Loopback HTTP server with per-path scripted responses."""
    handlers = {}

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            status, headers, body = handlers.get(
                self.path, (404, {}, b"not found"))
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", handlers
    server.shutdown()


def _jpeg_bytes(size=(64, 48)):
    buf = io.BytesIO()
    Image.new("RGB", size, (1, 2, 3)).save(buf, format="JPEG")
    return buf.getvalue()


# -- local roots ------------------------------------------------------------


def test_local_fixture_allowed(loaded, image_path):
    resp = _predict(loaded, str(image_path))
    assert resp.status_code == 200


def test_local_outside_roots_denied(loaded, tmp_path):
    allowed = tmp_path / "allowed"
    denied_dir = tmp_path / "denied"
    allowed.mkdir()
    denied_dir.mkdir()
    (allowed / "a.jpg").write_bytes(_jpeg_bytes())
    target = denied_dir / "b.jpg"
    target.write_bytes(_jpeg_bytes())
    _put(loaded, "source_local_roots", [str(allowed)])
    assert _predict(loaded, str(target)).status_code == 422
    resp = _predict(loaded, str(allowed / "a.jpg"))
    assert resp.status_code == 200


def test_local_empty_roots_deny_all(loaded, image_path):
    _put(loaded, "source_local_roots", [])
    resp = _predict(loaded, str(image_path))
    assert resp.status_code == 422
    assert "not permitted" in resp.json()["error"]["message"]


def test_local_traversal_denied(loaded, tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside.jpg"
    root.mkdir()
    outside.write_bytes(_jpeg_bytes())
    _put(loaded, "source_local_roots", [str(root)])
    resp = _predict(loaded, str(root / ".." / "outside.jpg"))
    assert resp.status_code == 422
    assert "not permitted" in resp.json()["error"]["message"]


def test_local_missing_and_error_sanitized(loaded, tmp_path):
    missing = tmp_path / "no-such-secret-name.jpg"
    resp = _predict(loaded, str(missing))
    assert resp.status_code == 422
    assert str(tmp_path) not in resp.text
    assert "no-such-secret-name" not in resp.text


def test_local_byte_cap(loaded, tmp_path):
    big = tmp_path / "big.jpg"
    big.write_bytes(b"\xff\xd8" + b"x" * 2048)
    _put(loaded, "max_upload_bytes", 100)
    resp = _predict(loaded, str(big))
    assert resp.status_code == 413


# -- network destinations ----------------------------------------------------


def test_http_literal_private_denied(loaded):
    for url in ("http://192.168.9.9/img.jpg", "http://10.1.2.3/img.jpg",
                    "http://127.0.0.1:8000/img.jpg",
                    "http://169.254.169.254/latest/meta-data"):
        resp = _predict(loaded, url)
        assert resp.status_code == 422, url
        assert "not permitted" in resp.json()["error"]["message"]
        assert url not in resp.text


def test_http_allowed_loopback(loaded, http_server):
    base, handlers = http_server
    handlers["/img.jpg"] = (200, {"Content-Type": "image/jpeg"}, _jpeg_bytes())
    _put(loaded, "source_allowed_hosts", ["127.0.0.1"])
    resp = _predict(loaded, f"{base}/img.jpg")
    assert resp.status_code == 200, resp.text
    assert resp.json()["image"] == {"width": 64, "height": 48}


def test_http_private_allowed_by_flag(loaded, http_server):
    base, handlers = http_server
    handlers["/img.jpg"] = (200, {"Content-Type": "image/jpeg"}, _jpeg_bytes())
    _put(loaded, "source_allow_private", True)
    resp = _predict(loaded, f"{base}/img.jpg")
    assert resp.status_code == 200


def test_http_redirect_to_denied_target(loaded, http_server):
    base, handlers = http_server
    handlers["/go"] = (302, {"Location": "http://169.254.169.254/x"}, b"")
    _put(loaded, "source_allowed_hosts", ["127.0.0.1"])
    resp = _predict(loaded, f"{base}/go")
    assert resp.status_code == 422
    assert "not permitted" in resp.json()["error"]["message"]
    assert "169.254" not in resp.text


def test_http_redirect_to_allowed_target(loaded, http_server):
    base, handlers = http_server
    handlers["/go"] = (302, {"Location": "/img.jpg"}, b"")
    handlers["/img.jpg"] = (200, {"Content-Type": "image/jpeg"},
                          _jpeg_bytes())
    _put(loaded, "source_allowed_hosts", ["127.0.0.1"])
    resp = _predict(loaded, f"{base}/go")
    assert resp.status_code == 200


def test_http_redirect_scheme_denied(loaded, http_server):
    base, handlers = http_server
    handlers["/go"] = (302, {"Location": "file:///etc/passwd"}, b"")
    _put(loaded, "source_allowed_hosts", ["127.0.0.1"])
    resp = _predict(loaded, f"{base}/go")
    assert resp.status_code == 422
    assert "not permitted" in resp.json()["error"]["message"]


def test_http_redirect_loop_bounded(loaded, http_server):
    base, handlers = http_server
    handlers["/loop"] = (302, {"Location": "/loop"}, b"")
    _put(loaded, "source_allowed_hosts", ["127.0.0.1"])
    resp = _predict(loaded, f"{base}/loop")
    assert resp.status_code == 422


def test_http_content_length_cap(loaded, http_server):
    base, handlers = http_server
    handlers["/big"] = (200, {"Content-Length": "5000"}, b"y" * 5000)
    _put(loaded, "source_allowed_hosts", ["127.0.0.1"])
    _put(loaded, "max_upload_bytes", 100)
    resp = _predict(loaded, f"{base}/big")
    assert resp.status_code == 413


def test_http_streamed_body_cap(loaded, http_server):
    base, handlers = http_server
    # No Content-Length: the cap must abort the read mid-stream.
    handlers["/stream"] = (200, {}, b"z" * 5000)
    _put(loaded, "source_allowed_hosts", ["127.0.0.1"])
    _put(loaded, "max_upload_bytes", 100)
    resp = _predict(loaded, f"{base}/stream")
    assert resp.status_code == 413


def test_http_fetch_error_sanitized(loaded, http_server):
    base, _ = http_server
    _put(loaded, "source_allowed_hosts", ["127.0.0.1"])
    resp = _predict(loaded, f"{base}/missing-secret-path")
    assert resp.status_code == 422
    assert base not in resp.text
    assert "missing-secret-path" not in resp.text


# -- pixel bound before decode ------------------------------------------------


def test_pixel_cap_before_decode(loaded, tmp_path):
    """A truncated PNG still reports dimensions; the pixel cap must fire
    before full decode fails."""
    buf = io.BytesIO()
    Image.new("RGB", (64, 48)).save(buf, format="PNG")
    p = tmp_path / "trunc.png"
    p.write_bytes(buf.getvalue()[:64])  # IHDR intact, raster missing
    _put(loaded, "max_image_pixels", 1)
    resp = _predict(loaded, str(p))
    assert resp.status_code == 413, resp.text
    _put(loaded, "max_image_pixels", 50_000_000)
    resp = _predict(loaded, str(p))
    assert resp.status_code == 422  # same file, decode now attempted


# -- stream admission ----------------------------------------------------------


def test_stream_private_destination_denied(client, rtsp):
    resp = client.post("/api/v1/stream/",
                       json={"source": "rtsp://192.168.9.9/x"})
    assert resp.status_code == 422
    assert "not permitted" in resp.json()["error"]["message"]
    assert "192.168" not in resp.text


def test_stream_loopback_and_linklocal_denied(client, rtsp):
    for url in ("rtsp://127.0.0.1:554/x", "rtsp://169.254.1.1/x"):
        resp = client.post("/api/v1/stream/", json={"source": url})
        assert resp.status_code == 422, url


def test_stream_allowlisted_camera(client, rtsp):
    _put(client, "source_allowed_hosts", ["192.168.9.9"])
    resp = client.post("/api/v1/stream/",
                       json={"source": "rtsp://192.168.9.9/x"})
    assert resp.status_code == 202


def test_stream_allowlisted_cidr(client, rtsp):
    _put(client, "source_allowed_hosts", ["192.168.9.0/24"])
    resp = client.post("/api/v1/stream/",
                       json={"source": "rtsp://192.168.9.9/x"})
    assert resp.status_code == 202


def test_stream_private_allowed_by_flag(client, rtsp):
    _put(client, "source_allow_private", True)
    resp = client.post("/api/v1/stream/",
                       json={"source": "rtsp://192.168.9.9/x"})
    assert resp.status_code == 202


def test_stream_unresolvable_host_permitted(client, rtsp):
    """An unprovable destination class defers to the capture connect."""
    resp = client.post("/api/v1/stream/",
                       json={"source": "rtsp://cam.invalid.local/x"})
    assert resp.status_code == 202


@pytest.fixture()
def rtsp(monkeypatch):
    class _Fake:
        source_type = "rtsp"

        def open_stream(self, locator, options, credentialed_locator):
            raise AssertionError("should not open during policy tests")

    fake = _Fake()
    monkeypatch.setitem(CAPTURE_REGISTRY._adapters, "rtsp", fake)
    return fake

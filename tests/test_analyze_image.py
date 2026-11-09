"""v1.5 POST /api/v1/analyze/image — multipart still analysis."""

from __future__ import annotations

import io
import json

from PIL import Image

SIMPLE = {"id": "p", "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}
ANNOTATED = {"id": "pa", "name": "A",
             "stages": [{"id": "i", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"},
                        {"id": "ann", "kind": "annotate",
                         "portable": {"annotation": {}}}]}


def _bytes(fmt="JPEG", size=(16, 16), color=(9, 9, 9)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def _pipeline(client, body=SIMPLE):
    client.post("/api/v1/pipeline/", json=body, headers={"If-Match": "*"})


def test_jpeg_json_default(client):
    _pipeline(client)
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")},
        data={"request": json.dumps({"pipeline_id": "p"})},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["observations"][0]["task"] == "detection"
    assert body["observations"][0]["pipeline_id"] == "p"
    assert body["media_id"] is None


def test_png_accepted(client):
    _pipeline(client)
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.png", _bytes("PNG"), "image/png")},
        data={"request": json.dumps({"pipeline_id": "p"})},
    )
    assert resp.status_code == 200
    assert resp.json()["observations"][0]["items"]


def test_accept_image_jpeg_returns_rendered(client):
    _pipeline(client)
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")},
        data={"request": json.dumps({"pipeline_id": "p"})},
        headers={"Accept": "image/jpeg"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(resp.content))
    assert img.size == (16, 16)


def test_accept_other_type_falls_back_to_json(client):
    _pipeline(client)
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")},
        data={"request": json.dumps({"pipeline_id": "p"})},
        headers={"Accept": "image/png"},
    )
    assert resp.status_code == 200
    assert "json" in resp.headers["content-type"]


def test_annotation_pipeline_renders_presentation(client):
    _pipeline(client, ANNOTATED)
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")},
        data={"request": json.dumps({"pipeline_id": "pa"})},
        headers={"Accept": "image/jpeg"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


def test_missing_file_422_or_400(client):
    _pipeline(client)
    resp = client.post("/api/v1/analyze/image",
                       data={"request": json.dumps({"pipeline_id": "p"})})
    assert resp.status_code in (400, 422)


def test_bad_request_json_422(client):
    _pipeline(client)
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")},
        data={"request": "{not-json"},
    )
    assert resp.status_code == 422


def test_bad_request_schema_422(client):
    _pipeline(client)
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")},
        data={"request": json.dumps({"pipeline_id": "p", "bogus": 1})},
    )
    assert resp.status_code == 422


def test_no_pipeline_and_no_default_422(client):
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")})
    assert resp.status_code == 422


def test_unknown_pipeline_404(client):
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")},
        data={"request": json.dumps({"pipeline_id": "ghost"})})
    assert resp.status_code == 404


def test_wrong_media_type_415(client):
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.txt", b"not-an-image", "text/plain")},
        data={"request": json.dumps({"pipeline_id": "p"})})
    assert resp.status_code == 415


def test_corrupt_image_422(client):
    bad = b"\xff\xd8" + b"junkjunkjunk" * 50  # jpeg magic, garbage body
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", bad, "image/jpeg")},
        data={"request": json.dumps({"pipeline_id": "p"})})
    assert resp.status_code in (415, 422)


def test_oversize_413(client, monkeypatch):
    _pipeline(client)
    big = b"\xff\xd8" + b"\x00" * (1_073_741_824 + 1)  # > 1 GiB default cap
    # avoid actually shipping 1GiB: lower the cap via settings
    client.put("/api/v1/setting/max_upload_bytes",
               json={"value": 128}, headers={"If-Match": "*"})
    resp = client.post(
        "/api/v1/analyze/image",
        files={"image": ("a.jpg", _bytes("JPEG") * 8, "image/jpeg")},
        data={"request": json.dumps({"pipeline_id": "p"})})
    assert resp.status_code == 413


def test_no_media_side_effect(client):
    _pipeline(client)
    before = len(client.get("/api/v1/media/").json()["items"])
    client.post("/api/v1/analyze/image",
                files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")},
                data={"request": json.dumps({"pipeline_id": "p"})})
    assert len(client.get("/api/v1/media/").json()["items"]) == before


def test_correlation_headers(client):
    _pipeline(client)
    resp = client.post("/api/v1/analyze/image",
                       files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")},
                       data={"request": json.dumps({"pipeline_id": "p"})})
    assert resp.headers["x-opal-request-id"]
    assert resp.json()["observations"][0]["request_id"] == resp.headers["x-opal-request-id"]


def test_default_pipeline_used_when_request_omitted(client):
    _pipeline(client)
    client.put("/api/v1/setting/default_pipeline_id",
               json={"value": "p"}, headers={"If-Match": "*"})
    resp = client.post("/api/v1/analyze/image",
                       files={"image": ("a.jpg", _bytes("JPEG"), "image/jpeg")})
    assert resp.status_code == 200
    assert resp.json()["observations"][0]["pipeline_id"] == "p"

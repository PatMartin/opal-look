"""Upstream Capture resource: on-demand frame captures."""

import io

from PIL import Image

MEDIA = {"id": "ms", "name": "M", "kind": "media", "locator": "MID"}


def _source(client):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="JPEG")
    mid = client.post("/api/v1/media/", files={
        "file": ("x.jpg", buf.getvalue(), "image/jpeg")}).json()["id"]
    client.post("/api/v1/sources/",
                json={**MEDIA, "locator": mid}, headers={"If-Match": "*"})


def test_capture_crud(client):
    _source(client)
    resp = client.post("/api/v1/sources/ms/captures/",
                       json={"retain": True}, headers={"If-Match": "*"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"].startswith("cap-")
    assert body["source_id"] == "ms"
    assert body["mime_type"] == "image/jpeg"
    assert body["annotated"] is False
    assert body["frame_time"]
    cid = body["id"]
    assert client.get(f"/api/v1/captures/{cid}").json()["id"] == cid
    assert any(c["id"] == cid for c in client.get("/api/v1/captures/").json())
    content = client.get(f"/api/v1/captures/{cid}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/jpeg"
    assert len(content.content) > 100
    assert client.delete(f"/api/v1/captures/{cid}",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get(f"/api/v1/captures/{cid}").status_code == 404


def test_capture_no_retain_shorter_ttl(client):
    _source(client)
    a = client.post("/api/v1/sources/ms/captures/", json={"retain": False},
                    headers={"If-Match": "*"}).json()
    b = client.post("/api/v1/sources/ms/captures/", json={"retain": True},
                    headers={"If-Match": "*"}).json()
    assert a["expires_at"] < b["expires_at"]


def test_capture_unknown_source_404(client):
    resp = client.post("/api/v1/sources/nope/captures/",
                       json={"retain": True}, headers={"If-Match": "*"})
    assert resp.status_code == 404


def test_capture_annotate_requires_context(client):
    _source(client)
    resp = client.post("/api/v1/sources/ms/captures/",
                       json={"retain": True, "annotate": True},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    resp = client.post("/api/v1/sources/ms/captures/",
                       json={"retain": True, "annotate": True,
                             "observation_id": "ghost"},
                       headers={"If-Match": "*"})
    assert resp.status_code == 404


def test_capture_mutations_require_if_match(client):
    _source(client)
    assert client.post("/api/v1/sources/ms/captures/",
                       json={"retain": True}).status_code == 428
    cid = client.post("/api/v1/sources/ms/captures/",
                      json={"retain": True}, headers={"If-Match": "*"}).json()["id"]
    assert client.delete(f"/api/v1/captures/{cid}").status_code == 428


def test_capture_list_source_filter(client):
    _source(client)
    client.post("/api/v1/sources/ms/captures/", json={"retain": True},
                headers={"If-Match": "*"})
    assert client.get("/api/v1/captures/",
                      params={"source_id": "ms"}).json()
    assert client.get("/api/v1/captures/",
                      params={"source_id": "other"}).json() == []

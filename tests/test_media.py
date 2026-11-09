import io

import pytest
from PIL import Image


def _img(fmt="JPEG", size=(32, 24), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def _upload(client, data=None, filename="pic.jpg", ctype="image/jpeg"):
    data = _img() if data is None else data
    return client.post(
        "/api/v1/media/", files={"file": (filename, data, ctype)}
    )


def test_upload_jpeg(client):
    resp = _upload(client)
    assert resp.status_code == 201
    assert resp.headers["location"].startswith("/api/v1/media/media-")
    body = resp.json()
    assert body["kind"] == "image"
    assert body["mime_type"] == "image/jpeg"
    assert body["id"].startswith("media-")
    assert body["size_bytes"] > 0
    assert body["size_bytes"] > 0
    assert body["created_at"] < body["expires_at"]


def test_upload_png(client):
    resp = _upload(client, data=_img("PNG"), filename="p.png", ctype="image/png")
    assert resp.status_code == 201
    assert resp.json()["mime_type"] == "image/png"


def test_upload_text_bytes_415(client):
    resp = _upload(client, data=b"not an image")
    assert resp.status_code == 415


def test_upload_corrupt_jpeg_422(client):
    resp = _upload(client, data=b"\xff\xd8\xff\xe0" + b"\x00" * 32)
    assert resp.status_code == 422


def test_unsupported_type_415(client):
    resp = client.post("/api/v1/media/",
                       files={"file": ("x.bin", b"PK" + b"0" * 64,
                                        "application/zip")})
    assert resp.status_code == 415


def test_upload_mp4_201_video_kind(client):
    mp4 = b"\x00\x00\x00ftypmp42" + b"\x00" * 64
    resp = client.post("/api/v1/media/",
                       files={"file": ("v.mp4", mp4, "video/mp4")})
    assert resp.status_code == 201
    assert resp.json()["kind"] == "video"
    assert resp.json()["mime_type"] == "video/mp4"


def test_upload_empty_422(client):
    resp = _upload(client, data=b"")
    assert resp.status_code == 422


def test_upload_over_limit_413(client):
    client.patch(
        "/api/v1/setting/", json={"max_upload_bytes": 10}, headers={"If-Match": "*"}
    )
    resp = _upload(client)
    assert resp.status_code == 413


def test_filename_sanitized_v15(client):
    resp = _upload(client, filename="../../evil.jpg")
    assert resp.status_code == 201
    assert "/" not in resp.json()["id"]


def test_list_media_cursor(client):
    _upload(client)
    _upload(client)
    first = client.get("/api/v1/media/", params={"limit": 1}).json()
    assert len(first["items"]) == 1
    assert first["has_more"] is True
    assert first["next_cursor"]
    second = client.get(
        "/api/v1/media/", params={"limit": 1, "cursor": first["next_cursor"]}
    ).json()
    assert len(second["items"]) == 1
    assert second["items"][0]["id"] != first["items"][0]["id"]


def test_list_media_bad_cursor_422(client):
    resp = client.get("/api/v1/media/", params={"cursor": "garbage"})
    assert resp.status_code == 422


def test_get_media(client):
    mid = _upload(client).json()["id"]
    resp = client.get(f"/api/v1/media/{mid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == mid


def test_get_unknown_media_404(client):
    assert client.get("/api/v1/media/nope").status_code == 404


def test_delete_media(client):
    mid = _upload(client).json()["id"]
    resp = client.delete(f"/api/v1/media/{mid}")
    assert resp.status_code == 204
    assert client.get(f"/api/v1/media/{mid}").status_code == 404


def test_delete_unknown_media_404(client):
    assert client.delete("/api/v1/media/nope").status_code == 404


def test_expired_media_410(client):
    mid = _upload(client).json()["id"]
    store = client.app.state.store
    store._conn.execute(
        "UPDATE media SET expires_at = '2000-01-01T00:00:00Z' WHERE media_id = ?",
        (mid,),
    )
    assert client.get(f"/api/v1/media/{mid}").status_code == 410
    # Expired rows are excluded from listings too.
    assert client.get("/api/v1/media/").json()["items"] == []


def test_media_backed_source_lifecycle(client):
    mid = _upload(client).json()["id"]
    resp = client.post(
        "/api/v1/source/",
        json={
            "id": "vid-src",
            "name": "Video",
            "kind": "media",
            "locator": mid,
        },
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201
    assert resp.json()["state"] == "ready"
    assert "redacted_locator" in resp.json()

    # v1.5: media is pinned while a media source references it (409)
    assert client.delete(f"/api/v1/media/{mid}",
                         headers={"If-Match": "*"}).status_code == 409
    client.delete("/api/v1/source/vid-src", headers={"If-Match": "*"})
    assert client.delete(f"/api/v1/media/{mid}",
                         headers={"If-Match": "*"}).status_code == 204
    assert client.get(f"/api/v1/media/{mid}").status_code == 404

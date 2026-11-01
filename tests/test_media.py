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
    assert body["content_type"] == "image/jpeg"
    assert body["filename"] == "pic.jpg"
    assert body["width"] == 32 and body["height"] == 24
    assert body["size_bytes"] > 0
    assert body["created_at"] < body["expires_at"]


def test_upload_png(client):
    resp = _upload(client, data=_img("PNG"), filename="p.png", ctype="image/png")
    assert resp.status_code == 201
    assert resp.json()["content_type"] == "image/png"


def test_upload_text_bytes_415(client):
    resp = _upload(client, data=b"not an image")
    assert resp.status_code == 415


def test_upload_corrupt_jpeg_422(client):
    resp = _upload(client, data=b"\xff\xd8\xff\xe0" + b"\x00" * 32)
    assert resp.status_code == 422


def test_upload_mp4_415_no_decoder(client):
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    resp = _upload(client, data=mp4, filename="v.mp4", ctype="video/mp4")
    assert resp.status_code == 415


def test_upload_empty_422(client):
    resp = _upload(client, data=b"")
    assert resp.status_code == 422


def test_upload_over_limit_413(client):
    client.patch(
        "/api/v1/settings/", json={"max_upload_bytes": 10}, headers={"If-Match": "*"}
    )
    resp = _upload(client)
    assert resp.status_code == 413


def test_filename_sanitized(client):
    resp = _upload(client, filename="../../evil.jpg")
    assert resp.status_code == 201
    assert "/" not in resp.json()["filename"]


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
    assert second["items"][0]["media_id"] != first["items"][0]["media_id"]


def test_list_media_bad_cursor_422(client):
    resp = client.get("/api/v1/media/", params={"cursor": "garbage"})
    assert resp.status_code == 422


def test_get_media(client):
    mid = _upload(client).json()["media_id"]
    resp = client.get(f"/api/v1/media/{mid}")
    assert resp.status_code == 200
    assert resp.json()["media_id"] == mid


def test_get_unknown_media_404(client):
    assert client.get("/api/v1/media/nope").status_code == 404


def test_media_content_download(client):
    data = _img()
    mid = _upload(client, data=data).json()["media_id"]
    resp = client.get(f"/api/v1/media/{mid}/content")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == data


def test_delete_media(client):
    mid = _upload(client).json()["media_id"]
    resp = client.delete(f"/api/v1/media/{mid}")
    assert resp.status_code == 204
    assert client.get(f"/api/v1/media/{mid}").status_code == 404


def test_delete_unknown_media_404(client):
    assert client.delete("/api/v1/media/nope").status_code == 404


def test_expired_media_410(client):
    mid = _upload(client).json()["media_id"]
    store = client.app.state.store
    store._conn.execute(
        "UPDATE media SET expires_at = '2000-01-01T00:00:00Z' WHERE media_id = ?",
        (mid,),
    )
    assert client.get(f"/api/v1/media/{mid}").status_code == 410
    assert client.get(f"/api/v1/media/{mid}/content").status_code == 410
    # Expired rows are excluded from listings too.
    assert client.get("/api/v1/media/").json()["items"] == []


def test_media_backed_source_lifecycle(client):
    mid = _upload(client).json()["media_id"]
    resp = client.post(
        "/api/v1/sources/",
        json={
            "source_id": "vid-src",
            "name": "Video",
            "type": "media",
            "locator": mid,
        },
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201
    assert resp.json()["available"] is True
    assert resp.json()["live"] is False

    client.delete(f"/api/v1/media/{mid}")
    src = client.get("/api/v1/sources/vid-src").json()
    assert src["available"] is False

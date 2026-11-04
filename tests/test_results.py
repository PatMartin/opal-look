import io

import pytest
from PIL import Image


def _img(size=(40, 30), color=(5, 200, 60)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def result(client):
    mid = client.post(
        "/api/v1/media/", files={"file": ("p.jpg", _img(), "image/jpeg")}
    ).json()["id"]
    body = client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "media", "media_id": mid},
            "model_id": "synthetic-vision",
            "task": "detection",
        },
    ).json()
    return body


def test_result_in_history(client, result):
    resp = client.get("/api/v1/results/")
    assert resp.status_code == 200
    body = resp.json()
    assert any(i["result_id"] == result["result_id"] for i in body["items"])
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_get_result(client, result):
    resp = client.get(f"/api/v1/results/{result['result_id']}")
    assert resp.status_code == 200
    assert resp.json()["result_id"] == result["result_id"]


def test_get_unknown_result_404(client):
    assert client.get("/api/v1/results/nope").status_code == 404


def test_unstored_result_not_in_history(client):
    mid = client.post(
        "/api/v1/media/", files={"file": ("p.jpg", _img(), "image/jpeg")}
    ).json()["id"]
    body = client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "media", "media_id": mid},
            "model_id": "synthetic-vision",
            "task": "detection",
            "store_result": False,
        },
    ).json()
    assert client.get(f"/api/v1/results/{body['result_id']}").status_code == 404


def test_delete_result(client, result):
    resp = client.delete(f"/api/v1/results/{result['result_id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/v1/results/{result['result_id']}").status_code == 404


def test_results_filters(client, result):
    assert client.get("/api/v1/results/", params={"task": "detection"}).json()["items"]
    assert client.get("/api/v1/results/", params={"task": "ocr"}).json()["items"] == []
    assert client.get("/api/v1/results/", params={"model_id": "synthetic-vision"}).json()["items"]
    assert client.get("/api/v1/results/", params={"source_id": "x"}).json()["items"] == []


def test_results_task_incompatible_filters(client, result):
    assert client.get(
        "/api/v1/results/", params={"task": "ocr", "class_label": "person"}
    ).status_code == 422
    assert client.get(
        "/api/v1/results/", params={"task": "detection", "text": "x"}
    ).status_code == 422
    assert client.get(
        "/api/v1/results/", params={"class_label": "p", "text": "x"}
    ).status_code == 422


def test_results_cursor_pagination(client, result):
    # Second result for paging.
    mid = client.post(
        "/api/v1/media/", files={"file": ("p2.jpg", _img(), "image/jpeg")}
    ).json()["id"]
    client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "media", "media_id": mid},
            "model_id": "synthetic-vision",
            "task": "detection",
        },
    )
    page1 = client.get("/api/v1/results/", params={"limit": 1}).json()
    assert len(page1["items"]) == 1 and page1["has_more"]
    page2 = client.get(
        "/api/v1/results/", params={"limit": 1, "cursor": page1["next_cursor"]}
    ).json()
    assert len(page2["items"]) == 1
    assert page2["items"][0]["result_id"] != page1["items"][0]["result_id"]


def test_results_bad_cursor_422(client):
    assert client.get("/api/v1/results/", params={"cursor": "junk"}).status_code == 422


def test_snapshot_ephemeral_jpeg(client, result):
    resp = client.post(
        f"/api/v1/results/{result['result_id']}/snapshot", json={"annotated": True}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content[:2] == b"\xff\xd8"


def test_snapshot_retain(client, result):
    resp = client.post(
        f"/api/v1/results/{result['result_id']}/snapshot",
        json={"annotated": True, "retain": True},
    )
    assert resp.status_code == 201
    assert resp.headers["location"].startswith("/api/v1/snapshots/")
    body = resp.json()
    assert body["result_id"] == result["result_id"]
    assert body["annotated"] is True
    assert body["content_type"] == "image/jpeg"
    assert body["width"] == 40 and body["height"] == 30
    sid = body["snapshot_id"]

    assert client.get(f"/api/v1/snapshots/{sid}").status_code == 200
    content = client.get(f"/api/v1/snapshots/{sid}/content")
    assert content.status_code == 200 and content.content[:2] == b"\xff\xd8"
    assert client.get("/api/v1/snapshots/").json()["items"]
    assert client.get(
        "/api/v1/snapshots/", params={"result_id": result["result_id"]}
    ).json()["items"]
    assert client.delete(f"/api/v1/snapshots/{sid}").status_code == 204
    assert client.get(f"/api/v1/snapshots/{sid}").status_code == 404


def test_snapshot_unknown_result_404(client):
    resp = client.post("/api/v1/results/nope/snapshot", json={})
    assert resp.status_code == 404


def test_snapshot_evicted_frame_409(client):
    mid = client.post(
        "/api/v1/media/", files={"file": ("p.jpg", _img(), "image/jpeg")}
    ).json()["id"]
    body = client.post(
        "/api/v1/analyze",
        json={
            "input": {"kind": "media", "media_id": mid},
            "model_id": "synthetic-vision",
            "task": "detection",
            "store_result": False,
        },
    ).json()
    # Evict manually to simulate cache expiry.
    client.app.state.frame_cache._entries.clear()
    resp = client.post(f"/api/v1/results/{body['result_id']}/snapshot", json={})
    assert resp.status_code == 404  # ephemeral + evicted -> unknown


def test_snapshot_stored_result_evicted_409(client, result):
    client.app.state.frame_cache._entries.clear()
    resp = client.post(f"/api/v1/results/{result['result_id']}/snapshot", json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "frame_unavailable"


def test_expired_result_410(client, result):
    store = client.app.state.store
    store._conn.execute(
        "UPDATE results SET expires_at = '2000-01-01T00:00:00Z' WHERE result_id = ?",
        (result["result_id"],),
    )
    assert client.get(f"/api/v1/results/{result['result_id']}").status_code == 410
    assert client.get("/api/v1/results/").json()["items"] == []

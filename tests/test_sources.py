RTSP = {
    "id": "cam-1",
    "name": "Yard camera",
    "kind": "rtsp",
    "locator": "rtsp://192.168.1.50:554/stream1",
    "enabled": True,
}


def test_list_sources_empty(client):
    resp = client.get("/api/v1/source/")
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["etag"].startswith('"')


def test_create_rtsp_source(client):
    resp = client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    assert resp.status_code == 201
    assert resp.headers["location"] == "/api/v1/source/cam-1"
    body = resp.json()
    assert body["state"] == "ready"
    assert body["enabled"] is True
    assert "zones" not in body
    assert body["capabilities"]
    # locator is redacted: scheme://authority only, no path/userinfo.
    assert body["redacted_locator"] == "rtsp://192.168.1.50:554/…"
    assert "stream1" not in body["redacted_locator"]


def test_create_source_requires_if_match(client):
    resp = client.post("/api/v1/source/", json=RTSP)
    assert resp.status_code == 428


def test_create_source_duplicate_409(client):
    client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    resp = client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    assert resp.status_code == 409


def test_rtsp_locator_with_credentials_422(client):
    resp = client.post(
        "/api/v1/source/",
        json={**RTSP, "locator": "rtsp://user:pass@192.168.1.50:554/x"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_rtsp_wrong_scheme_422(client):
    resp = client.post(
        "/api/v1/source/", json={**RTSP, "locator": "http://x/feed"}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_camera_url_locator_422(client):
    resp = client.post(
        "/api/v1/source/",
        json={**RTSP, "kind": "camera", "locator": "usb://cam0"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_media_source_unknown_media_404(client):
    resp = client.post(
        "/api/v1/source/",
        json={**RTSP, "kind": "media", "locator": "media-1"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 404


def test_host_video_source(client, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    resp = client.post(
        "/api/v1/source/",
        json={
            "id": "file-1",
            "name": "File",
            "kind": "file",
            "locator": str(video),
        },
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201
    body = resp.json()
    # No video decoder installed -> resource exists but is not usable.
    assert body["state"] == "disconnected"


def test_host_video_missing_path_still_registers(client):
    resp = client.post(
        "/api/v1/source/",
        json={
            "id": "gone",
            "name": "Gone",
            "kind": "file",
            "locator": "/nonexistent/clip.mp4",
        },
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201
    assert resp.json()["state"] in ("disconnected", "disabled")


def test_unknown_source_option_422(client):
    resp = client.post(
        "/api/v1/source/",
        json={**RTSP, "options": {"bogus": 1}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_known_source_option_ok(client):
    resp = client.post(
        "/api/v1/source/",
        json={**RTSP, "options": {"transport": "tcp"}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201


def test_get_source(client):
    client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    resp = client.get("/api/v1/source/cam-1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "cam-1"


def test_get_unknown_source_404(client):
    assert client.get("/api/v1/source/nope").status_code == 404


def test_patch_source(client):
    client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    resp = client.patch(
        "/api/v1/source/cam-1",
        json={"name": "Renamed", "enabled": False},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert resp.json()["enabled"] is False


def test_patch_source_requires_if_match(client):
    client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    resp = client.patch("/api/v1/source/cam-1", json={"name": "x"})
    assert resp.status_code == 428


def test_patch_source_null_422(client):
    client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    resp = client.patch(
        "/api/v1/source/cam-1", json={"enabled": None}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_delete_source(client):
    client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    resp = client.delete("/api/v1/source/cam-1", headers={"If-Match": "*"})
    assert resp.status_code == 204
    assert resp.headers["etag"].startswith('"')
    assert client.get("/api/v1/source/cam-1").status_code == 404







def test_rtsp_invalid_option_values_422(client):
    for options in ({"transport": "sctp"}, {"timeout_ms": 0}, {"timeout_ms": "x"}):
        resp = client.post(
            "/api/v1/source/",
            json={**RTSP, "options": options},
            headers={"If-Match": "*"},
        )
        assert resp.status_code == 422



def test_sources_list_enabled_filter(client):
    client.post("/api/v1/source/", json=RTSP, headers={"If-Match": "*"})
    client.post(
        "/api/v1/source/",
        json={**RTSP, "id": "cam-2", "enabled": False},
        headers={"If-Match": "*"},
    )
    enabled = client.get("/api/v1/source/", params={"enabled": "true"}).json()
    disabled = client.get("/api/v1/source/", params={"enabled": "false"}).json()
    assert [s["id"] for s in enabled] == ["cam-1"]
    assert [s["id"] for s in disabled] == ["cam-2"]







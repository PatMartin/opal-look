RTSP = {
    "source_id": "cam-1",
    "name": "Yard camera",
    "type": "rtsp",
    "locator": "rtsp://192.168.1.50:554/stream1",
    "enabled": True,
}


def test_list_sources_empty(client):
    resp = client.get("/api/v1/sources/")
    assert resp.status_code == 200
    assert resp.json() == []
    assert resp.headers["etag"].startswith('"')


def test_create_rtsp_source(client):
    resp = client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    assert resp.status_code == 201
    assert resp.headers["location"] == "/api/v1/sources/cam-1"
    body = resp.json()
    assert body["live"] is True
    assert body["available"] is False
    assert body["enabled"] is True
    assert body["width"] is None and body["duration_ms"] is None


def test_create_source_requires_if_match(client):
    resp = client.post("/api/v1/sources/", json=RTSP)
    assert resp.status_code == 428


def test_create_source_duplicate_409(client):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    assert resp.status_code == 409


def test_rtsp_locator_with_credentials_422(client):
    resp = client.post(
        "/api/v1/sources/",
        json={**RTSP, "locator": "rtsp://user:pass@192.168.1.50:554/x"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_rtsp_wrong_scheme_422(client):
    resp = client.post(
        "/api/v1/sources/", json={**RTSP, "locator": "http://x/feed"}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_camera_url_locator_422(client):
    resp = client.post(
        "/api/v1/sources/",
        json={**RTSP, "type": "camera", "locator": "usb://cam0"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_media_source_unknown_media_404(client):
    resp = client.post(
        "/api/v1/sources/",
        json={**RTSP, "type": "media", "locator": "media-1"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 404


def test_host_video_source(client, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    resp = client.post(
        "/api/v1/sources/",
        json={
            "source_id": "file-1",
            "name": "File",
            "type": "host_video",
            "locator": str(video),
        },
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["live"] is False
    assert body["available"] is True


def test_host_video_missing_path_still_registers(client):
    resp = client.post(
        "/api/v1/sources/",
        json={
            "source_id": "gone",
            "name": "Gone",
            "type": "host_video",
            "locator": "/nonexistent/clip.mp4",
        },
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201
    assert resp.json()["available"] is False


def test_unknown_source_option_422(client):
    resp = client.post(
        "/api/v1/sources/",
        json={**RTSP, "source_options": {"bogus": 1}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_known_source_option_ok(client):
    resp = client.post(
        "/api/v1/sources/",
        json={**RTSP, "source_options": {"transport": "tcp"}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201


def test_get_source(client):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.get("/api/v1/sources/cam-1")
    assert resp.status_code == 200
    assert resp.json()["source_id"] == "cam-1"


def test_get_unknown_source_404(client):
    assert client.get("/api/v1/sources/nope").status_code == 404


def test_patch_source(client):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.patch(
        "/api/v1/sources/cam-1",
        json={"name": "Renamed", "enabled": False},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert resp.json()["enabled"] is False


def test_patch_source_requires_if_match(client):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.patch("/api/v1/sources/cam-1", json={"name": "x"})
    assert resp.status_code == 428


def test_patch_source_null_422(client):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.patch(
        "/api/v1/sources/cam-1", json={"enabled": None}, headers={"If-Match": "*"}
    )
    assert resp.status_code == 422


def test_delete_source(client):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.delete("/api/v1/sources/cam-1", headers={"If-Match": "*"})
    assert resp.status_code == 204
    assert resp.headers["etag"].startswith('"')
    assert client.get("/api/v1/sources/cam-1").status_code == 404


def test_validate_source_disabled(client):
    client.post("/api/v1/sources/", json={**RTSP, "enabled": False}, headers={"If-Match": "*"})
    resp = client.post("/api/v1/sources/cam-1/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert any("disabled" in e for e in body["errors"])


def test_validate_source_unavailable_but_structurally_fine(client):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.post("/api/v1/sources/cam-1/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert any("unavailable" in e for e in body["errors"])


def test_validate_unknown_source_404(client):
    assert client.post("/api/v1/sources/nope/validate").status_code == 404


def test_devices_cameras_empty(client):
    resp = client.get("/api/v1/devices/cameras/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_sources_list_enabled_filter(client):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    client.post(
        "/api/v1/sources/",
        json={**RTSP, "source_id": "cam-2", "enabled": False},
        headers={"If-Match": "*"},
    )
    enabled = client.get("/api/v1/sources/", params={"enabled": "true"}).json()
    disabled = client.get("/api/v1/sources/", params={"enabled": "false"}).json()
    assert [s["source_id"] for s in enabled] == ["cam-1"]
    assert [s["source_id"] for s in disabled] == ["cam-2"]

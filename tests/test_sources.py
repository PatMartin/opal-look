RTSP = {
    "id": "cam-1",
    "name": "Yard camera",
    "kind": "rtsp",
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
    assert body["state"] == "ready"
    assert body["enabled"] is True
    assert body["zones"] == []
    # locator is redacted: scheme://authority only, no path/userinfo.
    assert body["redacted_locator"] == "rtsp://192.168.1.50:554/…"
    assert "stream1" not in body["redacted_locator"]


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
        json={**RTSP, "kind": "camera", "locator": "usb://cam0"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_media_source_unknown_media_404(client):
    resp = client.post(
        "/api/v1/sources/",
        json={**RTSP, "kind": "media", "locator": "media-1"},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 404


def test_host_video_source(client, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    resp = client.post(
        "/api/v1/sources/",
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
    assert body["state"] == "unavailable"


def test_host_video_missing_path_still_registers(client):
    resp = client.post(
        "/api/v1/sources/",
        json={
            "id": "gone",
            "name": "Gone",
            "kind": "file",
            "locator": "/nonexistent/clip.mp4",
        },
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201
    assert resp.json()["state"] in ("unavailable", "disabled")


def test_unknown_source_option_422(client):
    resp = client.post(
        "/api/v1/sources/",
        json={**RTSP, "options": {"bogus": 1}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_known_source_option_ok(client):
    resp = client.post(
        "/api/v1/sources/",
        json={**RTSP, "options": {"transport": "tcp"}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 201


def test_get_source(client):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.get("/api/v1/sources/cam-1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "cam-1"


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


def test_validate_source_unreachable(client, fake_rtsp):
    fake_rtsp.probe_result["available"] = False
    fake_rtsp.probe_result["message"] = "connect refused"
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.post("/api/v1/sources/cam-1/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert any("unreachable" in e for e in body["errors"])


def test_validate_source_live_probe_ok(client, fake_rtsp):
    client.post("/api/v1/sources/", json=RTSP, headers={"If-Match": "*"})
    resp = client.post("/api/v1/sources/cam-1/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["details"]["width"] == 320
    assert body["details"]["height"] == 240
    assert body["details"]["fps"] == 15.0
    assert fake_rtsp.probe_calls == ["rtsp://192.168.1.50:554/stream1"]


def test_validate_source_unresolved_credential(client, fake_rtsp, monkeypatch):
    monkeypatch.delenv("OPAL_LOOK_CRED_DRIVEWAY", raising=False)
    client.post(
        "/api/v1/sources/",
        json={**RTSP, "secret_ref": "driveway"},
        headers={"If-Match": "*"},
    )
    resp = client.post("/api/v1/sources/cam-1/validate")
    body = resp.json()
    assert body["valid"] is False
    assert any("not provisioned" in e for e in body["errors"])
    assert not fake_rtsp.probe_calls


def test_validate_source_credential_injected(client, fake_rtsp, monkeypatch):
    monkeypatch.setenv("OPAL_LOOK_CRED_DRIVEWAY", "alice:s3cret")
    client.post(
        "/api/v1/sources/",
        json={**RTSP, "secret_ref": "driveway"},
        headers={"If-Match": "*"},
    )
    resp = client.post("/api/v1/sources/cam-1/validate")
    assert resp.json()["valid"] is True
    assert fake_rtsp.probe_calls == ["rtsp://alice:s3cret@192.168.1.50:554/stream1"]


def test_rtsp_invalid_option_values_422(client):
    for options in ({"transport": "sctp"}, {"timeout_ms": 0}, {"timeout_ms": "x"}):
        resp = client.post(
            "/api/v1/sources/",
            json={**RTSP, "options": options},
            headers={"If-Match": "*"},
        )
        assert resp.status_code == 422


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
        json={**RTSP, "id": "cam-2", "enabled": False},
        headers={"If-Match": "*"},
    )
    enabled = client.get("/api/v1/sources/", params={"enabled": "true"}).json()
    disabled = client.get("/api/v1/sources/", params={"enabled": "false"}).json()
    assert [s["id"] for s in enabled] == ["cam-1"]
    assert [s["id"] for s in disabled] == ["cam-2"]


ZONES = [{
    "id": "front", "name": "Front", "kind": "polygon",
    "points": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.5, "y": 0.9}],
    "enabled": True,
}]


def test_create_source_with_zones_roundtrip(client):
    resp = client.post("/api/v1/sources/", json={**RTSP, "zones": ZONES},
                       headers={"If-Match": "*"})
    assert resp.status_code == 201
    assert resp.json()["zones"] == ZONES
    assert client.get("/api/v1/sources/cam-1").json()["zones"] == ZONES


def test_zone_validation(client):
    # duplicate ids -> 422
    resp = client.post("/api/v1/sources/",
                       json={**RTSP, "zones": ZONES + [dict(ZONES[0], name="B")]},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    # polygon with 2 points -> 422; line with 3 -> 422
    resp = client.post("/api/v1/sources/",
                       json={**RTSP, "zones": [dict(ZONES[0], points=ZONES[0]["points"][:2])]},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422
    resp = client.post(
        "/api/v1/sources/",
        json={**RTSP, "zones": [{"id": "l", "name": "L", "kind": "line",
                                 "points": [{"x": 0, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}]}]},
        headers={"If-Match": "*"})
    assert resp.status_code == 422
    # non-normalized point -> 422
    resp = client.post("/api/v1/sources/",
                       json={**RTSP, "zones": [dict(ZONES[0], points=[{"x": 2, "y": 0},
                                                                       {"x": 0, "y": 0},
                                                                       {"x": 0, "y": 1}])]},
                       headers={"If-Match": "*"})
    assert resp.status_code == 422


def test_patch_zones_replaces_atomically(client):
    client.post("/api/v1/sources/", json={**RTSP, "zones": ZONES}, headers={"If-Match": "*"})
    line = [{"id": "l1", "name": "Line", "kind": "line",
             "points": [{"x": 0, "y": 0}, {"x": 1, "y": 1}]}]
    resp = client.patch("/api/v1/sources/cam-1", json={"zones": line},
                        headers={"If-Match": "*"})
    assert resp.status_code == 200
    assert resp.json()["zones"] == line  # whole collection replaced
    resp = client.patch("/api/v1/sources/cam-1", json={"zones": []},
                        headers={"If-Match": "*"})
    assert resp.json()["zones"] == []

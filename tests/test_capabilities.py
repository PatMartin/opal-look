"""GET /api/v1/capabilities/ — catalog from real adapters/models/settings."""

from __future__ import annotations

REQUIRED_KEYS = {
    "tasks", "source_kinds", "media_types", "stream_transports",
    "export_formats", "limits",
}
ALLOWED_KEYS = REQUIRED_KEYS | {
    "filters", "visualization_modes", "supports_raw_stream",
    "supports_motion_gate", "supports_recording", "supports_monitoring",
    "supports_finite_video_analysis", "supports_remote_inference",
}
TASK_KEYS = {"task", "supported_inputs", "output_types",
             "controls_schema", "supports_streaming", "supports_tracking",
             "supports_annotation"}


def test_catalog_shape(client):
    resp = client.get("/api/v1/capabilities/")
    assert resp.status_code == 200
    body = resp.json()
    assert REQUIRED_KEYS <= set(body)
    assert set(body) <= ALLOWED_KEYS
    assert body["media_types"] == ["image/jpeg", "image/png"]
    assert body["export_formats"] == ["json"]
    assert body["limits"]["max_upload_bytes"] > 0


def test_catalog_tasks_come_from_models(client):
    body = client.get("/api/v1/capabilities/").json()
    tasks = {t["task"] for t in body["tasks"]}
    assert {"detection", "classification", "segmentation", "pose", "ocr"} <= tasks
    for desc in body["tasks"]:
        assert set(desc) <= TASK_KEYS
        assert desc["supported_inputs"] and desc["output_types"]


def test_catalog_reflects_registered_capture(client, fake_rtsp):
    body = client.get("/api/v1/capabilities/").json()
    assert "rtsp" in body["source_kinds"]
    assert "rtsp" in body["stream_transports"]
    assert "media" in body["source_kinds"]
    # No camera/http/host_video adapters are installed.
    assert "camera" not in body["source_kinds"]
    assert "http" not in body["source_kinds"]
    assert "host_video" not in body["source_kinds"]


def test_catalog_omits_tasks_when_no_available_models(client):
    client.patch("/api/v1/engines/synthetic", json={"enabled": False},
                 headers={"If-Match": "*"})
    body = client.get("/api/v1/capabilities/").json()
    assert body["tasks"] == []


def test_catalog_honest_support_flags(client):
    body = client.get("/api/v1/capabilities/").json()
    assert body["supports_recording"] is False
    assert body["supports_monitoring"] is False
    assert body["supports_remote_inference"] is False


def test_engine_schema_exact(client):
    eng = client.get("/api/v1/engines/synthetic").json()
    # Kernel OpalEngine: required fields present; additionalProperties allowed.
    assert {"engine_id", "name", "enabled", "available", "state", "tasks",
            "device_types", "options_schema", "options", "metadata",
            "version", "description"} <= set(eng)
    assert eng["state"] in ("ready", "unavailable", "disabled", "error")


def test_model_schema_exact(client):
    model = client.get("/api/v1/models/synthetic-vision").json()
    assert set(model) <= {
        "id", "engine_id", "display_name", "tasks", "state",
        "resource_label", "created_at",
    }
    assert model["state"] in ("ready", "unavailable", "disabled")


def test_model_create_unsupported_task_422(client):
    resp = client.post(
        "/api/v1/models/",
        json={"id": "m1", "engine_id": "synthetic",
              "resource_ref": "x", "tasks": ["teleport"]},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert details["unsupported_tasks"] == ["teleport"]


def test_model_create_bad_options_422(client):
    resp = client.post(
        "/api/v1/models/",
        json={"id": "m1", "engine_id": "synthetic",
              "resource_ref": "x", "tasks": ["detection"],
              "options": {"bogus": 1}},
        headers={"If-Match": "*"},
    )
    assert resp.status_code == 422


def test_model_patch_options_422_and_ok(client):
    resp = client.patch(
        "/api/v1/models/synthetic-vision", json={"options": {"bogus": 1}},
        headers={"If-Match": "*"})
    assert resp.status_code == 422
    resp = client.patch(
        "/api/v1/models/synthetic-vision", json={"options": {"seed": 7}},
        headers={"If-Match": "*"})
    assert resp.status_code == 200


def test_delete_referenced_model_409(client):
    """Models referenced by profiles cannot be deleted."""
    pid = client.post(
        "/api/v1/profiles/",
        json={"name": "p", "model_id": "synthetic-vision", "task": "detection"},
        headers={"If-Match": "*"},
    ).json()["profile_id"]
    assert client.delete("/api/v1/models/synthetic-vision",
                         headers={"If-Match": "*"}).status_code == 409
    # Cleanup: remove profile so other tests are unaffected.
    client.post(f"/api/v1/profiles/{pid}/activate", headers={"If-Match": "*"})
    client.delete(f"/api/v1/profiles/{pid}", headers={"If-Match": "*"})

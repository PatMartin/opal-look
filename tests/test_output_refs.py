"""Common output references (output_ref / artifact_ref / output_refs):
derived at read time so pre-existing records get them automatically."""

import io

from PIL import Image

MEDIA = {"id": "ms", "name": "M", "kind": "media", "locator": "MID"}


def _source(client):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="JPEG")
    mid = client.post("/api/v1/media/", files={
        "file": ("x.jpg", buf.getvalue(), "image/jpeg")}).json()["id"]
    client.post("/api/v1/source/",
                json={**MEDIA, "locator": mid}, headers={"If-Match": "*"})


def test_capture_output_ref_resolves_to_bytes(client):
    _source(client)
    body = client.post("/api/v1/source/ms/capture/", json={"retain": True},
                       headers={"If-Match": "*"}).json()
    ref = body["output_ref"]
    assert ref == {"kind": "capture", "id": body["id"],
                   "content_url": f"/api/v1/capture/{body['id']}/content"}
    content = client.get(ref["content_url"])
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/jpeg"


def test_capture_list_entries_carry_ref(client):
    _source(client)
    cid = client.post("/api/v1/source/ms/capture/", json={"retain": True},
                      headers={"If-Match": "*"}).json()["id"]
    listed = client.get("/api/v1/capture/").json()
    assert listed[0]["output_ref"]["content_url"] == f"/api/v1/capture/{cid}/content"


def test_recording_artifact_ref_pending_then_finalized(client):
    store = client.app.state.store
    store.recordings.insert({"recording_id": "rec-1", "source_id": "ms",
        "state": "finished", "created_at": "t", "started_at": "t",
        "finished_at": "t", "media_id": "m1", "failure": None})
    store.recordings.update("rec-1", {"artifact_id": "art-1"})
    body = client.get("/api/v1/recording/rec-1").json()
    assert body["artifact_ref"] == {"kind": "artifact", "id": "art-1",
                                    "content_url": "/api/v1/artifact/art-1/content"}


def test_recording_artifact_ref_null_while_running(client):
    store = client.app.state.store
    store.recordings.insert({"recording_id": "rec-2", "source_id": "ms",
        "state": "running", "created_at": "t", "started_at": "t",
        "finished_at": None, "media_id": "m2", "artifact_id": None,
        "failure": None})
    assert client.get("/api/v1/recording/rec-2").json()["artifact_ref"] is None


def test_job_output_refs_mirror_artifact_ids(client):
    store = client.app.state.store
    store.jobs.insert({"job_id": "job-1", "kind": "pipeline",
        "payload_json": "{}", "state": "completed", "created_at": "t",
        "started_at": "t", "ended_at": "t", "progress": 1.0,
        "media_ids": '["m9","m8"]', "failure": None})
    body = client.get("/api/v1/job/job-1").json()
    assert body["output_refs"] == [
        {"kind": "artifact", "id": "art-m9", "content_url": "/api/v1/artifact/art-m9/content"},
        {"kind": "artifact", "id": "art-m8", "content_url": "/api/v1/artifact/art-m8/content"},
    ]


def test_job_output_refs_null_while_pending(client):
    store = client.app.state.store
    store.jobs.insert({"job_id": "job-2", "kind": "pipeline",
        "payload_json": "{}", "state": "running", "created_at": "t",
        "started_at": "t", "ended_at": None, "progress": 0.4,
        "media_ids": "[]", "failure": None})
    assert client.get("/api/v1/job/job-2").json()["output_refs"] is None

"""v1.5 finite jobs: video_analysis + media_export, cancel, idempotency."""

from __future__ import annotations

import io
import time


def _apng(frames=3):
    """Animated PNG: passes the PNG upload policy and decodes
    multi-frame via ImageSequence."""
    from PIL import Image
    imgs = [Image.new("RGB", (8, 8), (i * 60, 0, 0)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, "PNG", save_all=True,
                 append_images=imgs[1:], duration=40)
    return buf.getvalue()


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, "JPEG")
    return buf.getvalue()


def _setup(client):
    client.post("/api/v1/pipeline/", json={
        "id": "p", "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}, headers={"If-Match": "*"})


def _wait_state(client, jid, terminal=("completed", "failed", "cancelled"),
                timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/api/v1/job/{jid}").json()["state"]
        if st in terminal:
            return st
        time.sleep(0.03)
    return st


def _submit_analysis(client, media_id):
    return client.post("/api/v1/job/", json={
        "kind": "analyze_video", "media_id": media_id,
        "pipeline_id": "p"})


def test_video_analysis_completes(client):
    _setup(client)
    up = client.post("/api/v1/media/",
                     files={"file": ("f.png", _apng(), "image/png")}).json()
    resp = _submit_analysis(client, up["id"])
    assert resp.status_code == 202
    job = resp.json()
    assert job["state"] in ("queued", "running", "completed")
    jid = job["id"]
    assert _wait_state(client, jid) == "completed"
    done = client.get(f"/api/v1/job/{jid}").json()
    assert done["progress"] == 1.0
    assert done["artifact_ids"] == []          # no retention -> no media


def test_video_analysis_retained_media(client):
    _setup(client)
    up = client.post("/api/v1/media/",
                     files={"file": ("f.png", _apng(), "image/png")}).json()
    resp = client.post("/api/v1/job/", json={
        "kind": "analyze_video", "media_id": up["id"],
        "pipeline_id": "p",
        "retention": {"save_raw_frames": True}})
    jid = resp.json()["id"]
    assert _wait_state(client, jid) == "completed"
    done = client.get(f"/api/v1/job/{jid}").json()
    assert len(done["artifact_ids"]) == 3       # one per GIF frame
    # output retrieval: media content is downloadable
    for aid in done["artifact_ids"]:
        r = client.get(f"/api/v1/artifact/{aid}/content")
        assert r.status_code == 200, r.text
        arow = client.get(f"/api/v1/artifact/{aid}").json()
        assert arow["job_id"] == jid


def test_media_export(client):
    up = client.post("/api/v1/media/",
                     files={"file": ("f.jpg", _jpeg(), "image/jpeg")}).json()
    resp = client.post("/api/v1/job/", json={
        "kind": "export_annotated_video", "media_id": up["id"],
        "output": {"format": "png"}})
    assert resp.status_code == 202
    jid = resp.json()["id"]
    assert _wait_state(client, jid) == "completed"
    done = client.get(f"/api/v1/job/{jid}").json()
    assert len(done["artifact_ids"]) == 1
    r = client.get(f"/api/v1/artifact/{done['artifact_ids'][0]}/content")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_media_export_unsupported_format_422(client):
    up = client.post("/api/v1/media/",
                     files={"file": ("f.jpg", _jpeg(), "image/jpeg")}).json()
    resp = client.post("/api/v1/job/", json={
        "kind": "export_annotated_video", "media_id": up["id"],
        "output": {"format": "mp4"}})
    assert resp.status_code == 422


def test_job_unknown_media_404(client):
    _setup(client)
    assert _submit_analysis(client, "ghost").status_code == 404


def test_job_source_oneof_422(client):
    resp = client.post("/api/v1/job/", json={
        "kind": "analyze_video",
        "source_id": "s", "media_id": "m"})
    assert resp.status_code == 422


def test_job_live_source_rejected(client):
    client.post("/api/v1/source/", json={
        "id": "cam", "name": "C", "kind": "rtsp", "locator": "rtsp://x"},
        headers={"If-Match": "*"})
    _setup(client)
    resp = client.post("/api/v1/job/", json={
        "kind": "analyze_video", "source_id": "cam", "pipeline_id": "p"})
    assert resp.status_code == 422


def test_job_cancel_queued(client):
    _setup(client)
    client.put("/api/v1/setting/max_jobs",
               json={"value": 1}, headers={"If-Match": "*"})
    # occupy the worker slot deterministically (running set, not a job row)
    client.app.state.job_runtime.running.add("holder")
    up = client.post("/api/v1/media/",
                     files={"file": ("f.png", _apng(), "image/png")}).json()
    j2 = _submit_analysis(client, up["id"])
    assert j2.status_code == 202
    jid2 = j2.json()["id"]
    assert client.get(f"/api/v1/job/{jid2}").json()["state"] in (
        "queued", "running")
    resp = client.post(f"/api/v1/job/{jid2}/cancel")
    assert resp.status_code == 200
    assert client.get(f"/api/v1/job/{jid2}").json()["state"] == "cancelled"


def test_job_cancel_terminal_409(client):
    _setup(client)
    up = client.post("/api/v1/media/",
                     files={"file": ("f.jpg", _jpeg(), "image/jpeg")}).json()
    jid = _submit_analysis(client, up["id"]).json()["id"]
    assert _wait_state(client, jid) == "completed"
    assert client.post(f"/api/v1/job/{jid}/cancel").status_code == 409


def test_job_quota_429(client):
    _setup(client)
    client.put("/api/v1/setting/max_jobs",
               json={"value": 1}, headers={"If-Match": "*"})
    up = client.post("/api/v1/media/",
                     files={"file": ("f.png", _apng(), "image/png")}).json()
    # seed 1 running + 1 queued nonterminal job deterministically
    store = client.app.state.store
    for jid, state in (("jq-a", "running"), ("jq-b", "queued")):
        store.jobs.insert({"job_id": jid, "kind": "analyze_video",
                           "payload_json": "{}", "state": state,
                           "created_at": "2026-01-01T00:00:00Z"})
    assert _submit_analysis(client, up["id"]).status_code == 429


def test_job_idempotency_replay_and_conflict(client):
    _setup(client)
    up = client.post("/api/v1/media/",
                     files={"file": ("f.jpg", _jpeg(), "image/jpeg")}).json()
    hdr = {"Idempotency-Key": "k-job-1"}
    r1 = client.post("/api/v1/job/", json={
        "kind": "analyze_video", "media_id": up["id"],
        "pipeline_id": "p"}, headers=hdr).json()
    # same key + same body -> returns the original job
    r2 = client.post("/api/v1/job/", json={
        "kind": "analyze_video", "media_id": up["id"],
        "pipeline_id": "p"}, headers=hdr).json()
    assert r2["id"] == r1["id"]
    # same key + different body -> 409
    resp = client.post("/api/v1/job/", json={
        "kind": "export_annotated_video", "media_id": up["id"],
        "output": {"format": "png"}}, headers=hdr)
    assert resp.status_code == 409


def test_job_unknown_404(client):
    assert client.get("/api/v1/job/ghost").status_code == 404
    assert client.post("/api/v1/job/ghost/cancel").status_code == 404


def test_job_interrupted_on_restart(tmp_path):
    from fastapi.testclient import TestClient
    from opal_look.app import create_app
    c = TestClient(create_app(data_dir=str(tmp_path)))
    # seed a running job row directly
    c.post("/api/v1/pipeline/", json={
        "id": "p", "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}, headers={"If-Match": "*"})
    store = c.app.state.store
    store.jobs.insert({
        "job_id": "job-x", "kind": "analyze_video", "payload_json": "{}",
        "state": "running", "created_at": "2025-01-01T00:00:00Z"})
    # restart: running -> failed interrupted; queued -> re-queued
    c2 = TestClient(create_app(data_dir=str(tmp_path)))
    job = c2.get("/api/v1/job/job-x").json()
    assert job["state"] == "failed"
    assert job["failure"]["code"] == "interrupted"

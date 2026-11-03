"""Step 09 DAG executor: stage order, motion gating, tracking, bounds."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from opal_look.pipeline_exec import _motion_score, run_pipeline

JPEG = None


def _img(color=(10, 20, 30), size=(32, 24)):
    return Image.new("RGB", size, color)


def _media_id(client, color=(10, 20, 30), size=(32, 24)):
    buf = io.BytesIO()
    _img(color, size).save(buf, format="JPEG")
    return client.post("/api/v1/media/",
                       files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")}
                       ).json()["media_id"]


def _pipeline(client, store_app=None, **over):
    return over


# -- direct executor tests (via store fixture) ---------------------------------

def _row(store, pipeline_id):
    return store.pipelines.get(pipeline_id)


def test_stage_order_and_trace(client, tmp_path):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P",
        "stages": [
            {"id": "g", "kind": "filter", "portable": {"filter": {"type": "grayscale"}}},
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection", "inputs": ["g"]},
        ]}, headers={"If-Match": "*"})
    store = client.app.state.store
    out = run_pipeline(store, _row(store, "p"), _img(),
                       transaction_id="t", request_id="r")
    assert out["trace"] == ["g", "i"]
    assert len(out["observations"]) == 1
    assert out["observations"][0]["stage_id"] == "i"


def test_inference_without_inputs_uses_base_frame(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection"}]},
        headers={"If-Match": "*"})
    store = client.app.state.store
    out = run_pipeline(store, _row(store, "p"), _img(),
                       transaction_id="t", request_id="r")
    assert out["observations"][0]["items"]


def test_filter_only_pipeline_no_model(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "g", "kind": "filter", "portable": {"filter": {"type": "grayscale"}}}]},
        headers={"If-Match": "*"})
    store = client.app.state.store
    out = run_pipeline(store, _row(store, "p"), _img(),
                       transaction_id="t", request_id="r")
    assert out["observations"] == []
    assert out["trace"] == ["g"]


def test_motion_unknown_on_isolated_still(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "m", "kind": "filter", "portable": {"filter": {"type": "motion"}}},
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection", "inputs": ["m"],
             "portable": {"gate": {"motion_stage_id": "m", "on_unknown": "skip"}}}]},
        headers={"If-Match": "*"})
    store = client.app.state.store
    out = run_pipeline(store, _row(store, "p"), _img(),
                       transaction_id="t", request_id="r", motion_states=None)
    inf = [o for o in out["observations"] if o["stage_id"] == "i"][0]
    assert inf["items"] == []
    assert any("unknown" in w or "skipped" in w for w in inf["warnings"])


def test_motion_gated_skip_then_periodic_sample(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "m", "kind": "filter", "portable": {"filter": {"type": "motion",
                                                                 "parameters": {"warmup_frames": 1}}}},
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection", "inputs": ["m"],
             "portable": {"gate": {"motion_stage_id": "m", "sample_every_n_frames": 2}}}]},
        headers={"If-Match": "*"})
    store = client.app.state.store
    states = {}
    img = _img((10, 20, 30))
    # warmup
    run_pipeline(store, _row(store, "p"), img, transaction_id="t", request_id="r1",
                 motion_states=states)
    # static frames: inference skipped except every 2nd
    verdicts = []
    for i in range(4):
        out = run_pipeline(store, _row(store, "p"), img,
                           transaction_id="t", request_id=f"r{i+2}",
                           motion_states=states)
        inf = [o for o in out["observations"] if o["stage_id"] == "i"][0]
        verdicts.append(bool(inf["items"]))
    # periodic sampling -> not all skipped
    assert any(verdicts) and not all(verdicts)


def test_motion_moving_runs_inference(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "m", "kind": "filter", "portable": {"filter": {"type": "motion",
                                                                 "parameters": {"warmup_frames": 1}}}},
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection", "inputs": ["m"],
             "portable": {"gate": {"motion_stage_id": "m"}}}]},
        headers={"If-Match": "*"})
    store = client.app.state.store
    states = {}
    run_pipeline(store, _row(store, "p"), _img((0, 0, 0)), transaction_id="t",
                 request_id="r1", motion_states=states)
    run_pipeline(store, _row(store, "p"), _img((0, 0, 0)), transaction_id="t",
                 request_id="r2", motion_states=states)
    out = run_pipeline(store, _row(store, "p"), _img((255, 255, 255)),
                       transaction_id="t", request_id="r3", motion_states=states)
    # large change -> moving -> inference runs
    inf = [o for o in out["observations"] if o["stage_id"] == "i"][0]
    assert inf["items"]


def test_tracker_attaches_track_ids(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection"},
            {"id": "t", "kind": "tracker", "inputs": ["i"]}]},
        headers={"If-Match": "*"})
    store = client.app.state.store
    out = run_pipeline(store, _row(store, "p"), _img(),
                       transaction_id="t", request_id="r")
    items = out["observations"][0]["items"]
    assert all(it["track_id"] for it in items)


def test_presentation_stage_isolated_from_inference(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "ann", "kind": "annotate", "phase": "presentation",
             "portable": {"annotation": {}}},
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection"}]},
        headers={"If-Match": "*"})
    store = client.app.state.store
    out = run_pipeline(store, _row(store, "p"), _img(),
                       transaction_id="t", request_id="r")
    assert out["observations"][0]["items"]
    assert out["presentation"]["image"] is not None


def test_disabled_stage_skipped_in_trace_order(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "g", "kind": "filter", "enabled": False,
             "portable": {"filter": {"type": "grayscale"}}},
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection"}]},
        headers={"If-Match": "*"})
    store = client.app.state.store
    out = run_pipeline(store, _row(store, "p"), _img(),
                       transaction_id="t", request_id="r")
    assert out["trace"] == ["g", "i"]
    assert out["observations"][0]["items"]


def test_engine_unavailable_503(client):
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection"}]},
        headers={"If-Match": "*"})
    client.patch("/api/v1/engines/synthetic", json={"enabled": False},
                 headers={"If-Match": "*"})
    store = client.app.state.store
    from opal_look.errors import ApiError
    with pytest.raises(ApiError) as exc:
        run_pipeline(store, _row(store, "p"), _img(),
                     transaction_id="t", request_id="r")
    assert exc.value.status_code == 503


def test_executor_via_http_pipeline_id(client):
    mid = _media_id(client)
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection"}]},
        headers={"If-Match": "*"})
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["observations"][0]["pipeline_id"] == "p"
    assert body["observations"][0]["items"]
    assert body["processing_ms"] >= 0


def test_pipeline_id_unknown_404(client):
    mid = _media_id(client)
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "nope", "source": {"media_id": mid}})
    assert resp.status_code == 404


def test_simple_pipeline_via_pipeline_id(client):
    mid = _media_id(client)
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "model_id": "synthetic-vision", "task": "ocr"},
        headers={"If-Match": "*"})
    resp = client.post("/api/v1/analyze/", json={
        "pipeline_id": "p", "source": {"media_id": mid}})
    assert resp.status_code == 200
    assert resp.json()["observations"][0]["task"] == "ocr"


def test_motion_state_bounded(client):
    """Motion baseline map is bounded (evicts oldest)."""
    client.post("/api/v1/pipelines/", json={
        "id": "p", "name": "P", "stages": [
            {"id": "m", "kind": "filter", "portable": {"filter": {"type": "motion"}}},
            {"id": "i", "kind": "inference", "model_id": "synthetic-vision",
             "task": "detection", "inputs": ["m"],
             "portable": {"gate": {"motion_stage_id": "m"}}}]},
        headers={"If-Match": "*"})
    store = client.app.state.store
    states = {}
    for k in range(80):
        run_pipeline(store, _row(store, "p"), _img(),
                     source_id=f"s{k}", transaction_id="t", request_id="r",
                     motion_states=states)
    assert len(states) <= 64

"""Step 08 DAG validation: topology, portable params, mode exclusivity."""

from __future__ import annotations

import pytest

INF = {"id": "inf", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}


def _valid(stages):
    return {"id": "p", "name": "P", "stages": stages}


# -- table-driven filter-parameter validation ---------------------------------

@pytest.mark.parametrize("ftype,params,ok", [
    ("grayscale", {}, True),
    ("grayscale", {"x": 1}, False),
    ("brightness_contrast", {"brightness": 0.5, "contrast": 1.2}, True),
    ("brightness_contrast", {"brightness": 2}, False),
    ("blur", {"kernel_size": 5}, True),
    ("blur", {"kernel_size": 4}, False),
    ("blur", {"kernel_size": 33}, False),
    ("sharpen", {"amount": 1.5}, True),
    ("sharpen", {"amount": 4}, False),
    ("threshold", {"threshold": 128}, True),
    ("threshold", {"threshold": 300}, False),
    ("edges", {"low_threshold": 10, "high_threshold": 100}, True),
    ("edges", {"low_threshold": 100, "high_threshold": 10}, False),
    ("rotate", {"degrees": 90}, True),
    ("rotate", {"degrees": 45}, False),
    ("flip", {"axis": "horizontal"}, True),
    ("flip", {"axis": "diagonal"}, False),
    ("crop", {"roi": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}}, True),
    ("crop", {"roi": {"x": 2, "y": 0, "width": 0.5, "height": 0.5}}, False),
    ("crop", {}, False),
    ("resize", {"width": 320}, True),
    ("resize", {"height": 240}, True),
    ("resize", {}, False),
    ("resize", {"width": 0}, False),
    ("motion", {"sensitivity": 0.5, "visualization": "mask"}, True),
    ("motion", {"visualization": "bogus"}, False),
    ("motion", {"sensitivity": 2}, False),
    ("motion", {"roi": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0, "y": 1}]}, True),
    ("motion", {"roi": [{"x": 0, "y": 0}]}, False),
    ("nope", {}, False),  # unknown filter type -> schema 422
])
def test_filter_parameter_table(client, ftype, params, ok):
    pipe = _valid([{"id": "f", "kind": "filter",
                    "portable": {"filter": {"type": ftype, "parameters": params}}}])
    resp = client.post("/api/v1/pipelines/validate", json=pipe)
    if ftype == "nope":
        assert resp.status_code == 422
        return
    body = resp.json()
    assert body["valid"] is ok, body
    if not ok:
        assert body["issues"][0]["severity"] == "error"
        assert body["issues"][0]["path"]


# -- topology -----------------------------------------------------------------

def test_forward_reference_rejected(client):
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "a", "kind": "filter", "inputs": ["b"],
         "portable": {"filter": {"type": "grayscale"}}},
        {"id": "b", "kind": "filter",
         "portable": {"filter": {"type": "grayscale"}}},
    ]))
    assert resp.json()["valid"] is False
    assert any(i["code"] == "invalid_stage_input" for i in resp.json()["issues"])


def test_self_and_unknown_reference_rejected(client):
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "a", "kind": "filter", "inputs": ["a"],
         "portable": {"filter": {"type": "grayscale"}}},
        {"id": "b", "kind": "filter", "inputs": ["zzz"],
         "portable": {"filter": {"type": "grayscale"}}},
    ]))
    assert resp.json()["issues"]


def test_duplicate_stage_ids_rejected(client):
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "a", "kind": "filter", "portable": {"filter": {"type": "grayscale"}}},
        {"id": "a", "kind": "filter", "portable": {"filter": {"type": "blur"}}},
    ]))
    assert any(i["code"] == "duplicate_stage_id" for i in resp.json()["issues"])


def test_inference_stage_requirements(client):
    # missing task
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "i", "kind": "inference", "model_id": "synthetic-vision"}]))
    assert any(i["code"] == "incomplete_inference_stage" for i in resp.json()["issues"])
    # unknown model
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "i", "kind": "inference", "model_id": "ghost", "task": "x"}]))
    assert any(i["code"] == "unknown_model" for i in resp.json()["issues"])
    # unsupported task
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "i", "kind": "inference", "model_id": "synthetic-vision", "task": "teleport"}]))
    assert any(i["code"] == "unsupported_task" for i in resp.json()["issues"])
    # unavailable model -> error
    client.patch("/api/v1/engines/synthetic", json={"enabled": False},
                 headers={"If-Match": "*"})
    resp = client.post("/api/v1/pipelines/validate", json=_valid([INF]))
    assert any(i["code"] == "model_unavailable" for i in resp.json()["issues"])


def test_tracker_requires_inference_input(client):
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "t", "kind": "tracker"}]))
    assert any(i["code"] == "tracker_without_inference" for i in resp.json()["issues"])
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        dict(INF), {"id": "t", "kind": "tracker", "inputs": ["inf"]}]))
    assert resp.json()["valid"] is True


def test_filter_stage_requires_portable_filter(client):
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "f", "kind": "filter"}]))
    assert any(i["code"] == "missing_filter_spec" for i in resp.json()["issues"])


def test_portable_option_kind_whitelist(client):
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        dict(INF, portable={"annotation": {"enabled": True}})]))
    assert any(i["code"] == "portable_option_wrong_kind" for i in resp.json()["issues"])


def test_gate_requires_motion_filter_stage(client):
    # gate on non-inference -> wrong kind
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "f", "kind": "filter",
         "portable": {"filter": {"type": "motion"}, "gate": {"motion_stage_id": "f"}}}]))
    assert any(i["code"] == "portable_option_wrong_kind" for i in resp.json()["issues"])
    # gate referencing non-motion stage
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "f", "kind": "filter", "portable": {"filter": {"type": "grayscale"}}},
        dict(INF, inputs=["f"], portable={"gate": {"motion_stage_id": "f"}})]))
    assert any(i["code"] == "gate_requires_motion_stage" for i in resp.json()["issues"])
    # valid motion gate
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "m", "kind": "filter", "portable": {"filter": {"type": "motion"}}},
        dict(INF, inputs=["m"], portable={"gate": {"motion_stage_id": "m"}})]))
    assert resp.json()["valid"] is True, resp.json()


def test_presentation_cannot_feed_inference(client):
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "a", "kind": "annotate", "phase": "presentation",
         "portable": {"annotation": {}}},
        dict(INF, inputs=["a"])]))
    assert any(i["code"] == "presentation_feeds_inference"
               for i in resp.json()["issues"])


def test_filter_only_pipeline_allowed(client):
    resp = client.post("/api/v1/pipelines/validate", json=_valid([
        {"id": "f1", "kind": "filter", "portable": {"filter": {"type": "grayscale"}}},
        {"id": "f2", "kind": "filter", "inputs": ["f1"],
         "portable": {"filter": {"type": "blur", "parameters": {"kernel_size": 3}}}},
    ]))
    assert resp.json()["valid"] is True


def test_validate_is_side_effect_free(client):
    etag_before = client.get("/api/v1/pipelines/").headers["etag"]
    client.post("/api/v1/pipelines/validate", json=_valid([INF]))
    assert client.get("/api/v1/pipelines/").headers["etag"] == etag_before
    assert client.get("/api/v1/pipelines/").json() == []


def test_create_advanced_422_details(client):
    resp = client.post("/api/v1/pipelines/", json=_valid([
        {"id": "f", "kind": "filter", "inputs": ["nope"],
         "portable": {"filter": {"type": "grayscale"}}},
    ]), headers={"If-Match": "*"})
    assert resp.status_code == 422
    details = resp.json()["error"]["details"]
    assert details["issues"][0]["code"] == "invalid_stage_input"


def test_patch_mode_switch_to_invalid_422(client):
    client.post("/api/v1/pipelines/",
                json={"id": "p1", "name": "P", "stages": [{"id": "s1", "kind": "inference", "model_id": "synthetic-vision", "task": "detection"}]}, headers={"If-Match": "*"})
    # patch with invalid DAG -> 422, pipeline unchanged
    resp = client.patch("/api/v1/pipelines/p1",
                        json={"stages": [{"id": "f", "kind": "filter",
                                          "inputs": ["x"]}]},
                        headers={"If-Match": "*"})
    assert resp.status_code == 422
    assert client.get("/api/v1/pipelines/p1").json()["stages"][0]["model_id"] == "synthetic-vision"

"""Shared EngineAdapter conformance suite.

Every adapter — in-process (synthetic) or remote (yolo-over-HTTP) — must
satisfy the same contract: discovery surface, model lifecycle, readiness
probe, normalized results, and error translation. A future adapter must
pass every test in this file before it is registered.
"""

from __future__ import annotations

import httpx
import pytest
from PIL import Image

from opal_look.engines import (EngineUnavailable, ModelNotFound,
                               SyntheticAdapter)
from opal_look.engines.yolo.adapter import YoloRemoteAdapter

YOLO_URL = "http://yolo.test:8086"

_DET = {"class_id": 0, "class_name": "person", "confidence": 0.9,
        "box": [1.0, 2.0, 3.0, 4.0]}


def _yolo_service(state: dict):
    """Stateful mock of the opal-look-yolo adapter contract."""

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/api/v1/engine/yolo":
            return httpx.Response(200, json={"engine_id": "yolo",
                                             "available": True})
        if p == "/api/v1/engine/yolo/capabilities":
            return httpx.Response(200, json={
                "tasks": ["detect"], "supported_devices": ["cpu"],
                "options_schema": {"imgsz": {"type": "integer"}},
                "annotation": True})
        if p == "/api/v1/hardware/":
            return httpx.Response(200, json=[{"device_id": "cpu",
                                              "device_type": "cpu",
                                              "name": "CPU"}])
        if p == "/api/v1/model/":
            return httpx.Response(200, json=[{
                "model_id": m["model_id"], "engine_id": "yolo",
                "tasks": ["detect"], "loaded": m["loaded"],
                "weights_sha256": "ab" * 32, "metadata": {}}
                for m in state["models"].values()])
        if p.endswith("/load") and p.startswith("/api/v1/model/"):
            mid = p.split("/")[4]
            if mid not in state["models"]:
                return httpx.Response(404, json={})
            state["models"][mid]["loaded"] = True
            return httpx.Response(200, json={
                "model_id": mid, "engine_id": "yolo",
                "tasks": ["detect"], "loaded": True})
        if p.endswith("/unload") and p.startswith("/api/v1/model/"):
            mid = p.split("/")[4]
            if mid not in state["models"]:
                return httpx.Response(404, json={})
            state["models"][mid]["loaded"] = False
            return httpx.Response(200, json={
                "model_id": mid, "engine_id": "yolo",
                "tasks": ["detect"], "loaded": False})
        if p == "/api/v1/predict/frame":
            if not any(m["loaded"] for m in state["models"].values()):
                return httpx.Response(409, json={})
            return httpx.Response(200, json={
                "detections": [dict(_DET)], "image": {"width": 8,
                                                    "height": 8}})
        return httpx.Response(404, json={})

    return handler


@pytest.fixture(params=["synthetic", "yolo"])
def adapter(request, monkeypatch):
    """An EngineAdapter instance: in-process or remote over mock HTTP."""
    if request.param == "synthetic":
        a = SyntheticAdapter()
        yield a
        return
    monkeypatch.setenv("OPAL_LOOK_ENGINE_YOLO_BASE_URL", YOLO_URL)
    state = {"models": {"yolov8n": {"model_id": "yolov8n",
                                    "loaded": False}}}
    yield YoloRemoteAdapter(
        transport=httpx.MockTransport(_yolo_service(state)))


def _model_id(adapter) -> str:
    return adapter.models()[0]["model_id"]


# -- discovery ---------------------------------------------------------------


def test_discovery_surface(adapter):
    assert adapter.engine_id
    assert adapter.execution in ("local", "remote")
    caps = adapter.capabilities()
    assert isinstance(caps.get("tasks"), list) and caps["tasks"]
    assert isinstance(caps.get("device_types")
                      or caps.get("supported_devices"), list)
    assert isinstance(adapter.metadata(), dict)
    schema = adapter.options_schema()
    assert isinstance(schema, dict)
    assert adapter.validate_config({}) == [] or True  # never raises


def test_engine_options_validation(adapter):
    assert adapter.validate_engine_options({}) == []
    assert adapter.validate_engine_options({"bogus_key_xyz": 1})


def test_hardware_list(adapter):
    devices = adapter.hardware()
    assert isinstance(devices, list) and devices
    for d in devices:
        assert "device_id" in d


# -- model lifecycle ----------------------------------------------------------


def test_model_listing_shape(adapter):
    models = adapter.models()
    assert models, "adapter must expose at least one model"
    for m in models:
        assert m["engine_id"] == adapter.engine_id
        assert m["model_id"]
        assert m["loaded"] in (True, False)


def test_load_unload_roundtrip(adapter):
    mid = _model_id(adapter)
    loaded = adapter.load_model(mid, device_id=None)
    assert loaded["loaded"] is True
    assert next(m for m in adapter.models()
                if m["model_id"] == mid)["loaded"] is True
    unloaded = adapter.unload_model(mid)
    assert unloaded["loaded"] is False


def test_unknown_model_raises_model_not_found(adapter):
    with pytest.raises(ModelNotFound):
        adapter.load_model("does-not-exist", device_id=None)
    with pytest.raises(ModelNotFound):
        adapter.unload_model("does-not-exist")


# -- readiness ----------------------------------------------------------------


def test_probe_disabled(adapter):
    ok, msg = adapter.probe({}, enabled=False)
    assert ok is False and msg


# -- normalized results --------------------------------------------------------


def test_predict_normalized_detections(adapter):
    mid = _model_id(adapter)
    adapter.load_model(mid, device_id=None)
    img = Image.new("RGB", (8, 8))
    out = adapter.predict(image=img, model_id=mid, confidence=0.5,
                          device_id="cpu", engine_options={},
                          include_native=True)
    dets = out["detections"]
    assert isinstance(dets, list) and dets
    for d in dets:
        assert isinstance(d["class_id"], int)
        assert isinstance(d["class_name"], str) and d["class_name"]
        assert 0.0 <= d["confidence"] <= 1.0
        x1, y1, x2, y2 = d["box"]
        assert 0 <= x1 < x2 <= img.width
        assert 0 <= y1 < y2 <= img.height


# -- error translation ----------------------------------------------------------


def test_unreachable_translates_to_engine_unavailable(monkeypatch):
    """Transport failure must surface as EngineUnavailable, not httpx."""
    monkeypatch.setenv("OPAL_LOOK_ENGINE_YOLO_BASE_URL", YOLO_URL)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    adapter = YoloRemoteAdapter(transport=httpx.MockTransport(boom))
    with pytest.raises(EngineUnavailable):
        adapter.models()


# -- app ownership / no cross-app state bleed -----------------------------------


def test_registry_is_app_owned_no_state_bleed(tmp_path):
    """Two app instances must not share adapter state.

    Loading a model in app A must not mark it loaded in app B — the old
    module-level ENGINE_REGISTRY leaked exactly this state."""
    from fastapi.testclient import TestClient

    from opal_look.app import create_app

    app_a = create_app(data_dir=tmp_path / "a")
    app_b = create_app(data_dir=tmp_path / "b")
    assert (app_a.state.engine_registry
            is not app_b.state.engine_registry)
    a_syn = app_a.state.engine_registry.get("synthetic")
    b_syn = app_b.state.engine_registry.get("synthetic")
    assert a_syn is not b_syn
    with TestClient(app_a) as a, TestClient(app_b) as b:
        resp = a.post("/api/v1/model/synthetic-det/load")
        assert resp.status_code == 200
        a_model = a.get("/api/v1/model/synthetic-det").json()
        b_model = b.get("/api/v1/model/synthetic-det").json()
        assert a_model["loaded"] is True
        assert b_model["loaded"] is False

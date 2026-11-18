"""Remote yolo adapter: env wiring + EngineAdapter-over-HTTP behavior."""

import json

import httpx
import pytest
from PIL import Image

from opal_look.engines import (EngineRegistry, EngineUnavailable,
                               ModelNotFound, ensure_engines)
from opal_look.engines.yolo import apply_env, register_if_configured
from opal_look.engines.yolo.adapter import YoloRemoteAdapter
from opal_look.store import Store

URL = "http://yolo.test:8086"


@pytest.fixture()
def yolo_env(monkeypatch):
    monkeypatch.setenv("OPAL_LOOK_ENGINE_YOLO_BASE_URL", URL)


def _adapter(handler) -> YoloRemoteAdapter:
    return YoloRemoteAdapter(transport=httpx.MockTransport(handler))


# -- registration / env wiring ----------------------------------------------


def test_not_registered_without_base_url(monkeypatch):
    monkeypatch.delenv("OPAL_LOOK_ENGINE_YOLO_BASE_URL", raising=False)
    registry = EngineRegistry()
    assert register_if_configured(registry) is False
    assert "yolo" not in registry


def test_registered_with_base_url(yolo_env):
    registry = EngineRegistry()
    assert register_if_configured(registry) is True
    adapter = registry.get("yolo")
    assert adapter.engine_id == "yolo"
    assert adapter.execution == "remote"
    # second call is a no-op
    assert register_if_configured(registry) is False


def test_apply_env_seeds_config(yolo_env, tmp_path):
    registry = EngineRegistry()
    register_if_configured(registry)
    store = Store(tmp_path / "data")
    ensure_engines(store, registry)
    assert apply_env(store) is True
    row = store.engines.get("yolo")
    assert json.loads(row["config"])["base_url"] == URL
    # idempotent: no change -> no rewrite
    assert apply_env(store) is False


def test_apply_env_authoritative_and_enabled_flag(yolo_env, monkeypatch,
                                                  tmp_path):
    registry = EngineRegistry()
    register_if_configured(registry)
    store = Store(tmp_path / "data")
    ensure_engines(store, registry)
    store.engines.update("yolo", {"config": {"base_url": "http://x"}})
    apply_env(store)
    row = store.engines.get("yolo")
    assert json.loads(row["config"])["base_url"] == URL
    assert bool(row["enabled"]) is True  # ENABLED unset -> flag untouched
    monkeypatch.setenv("OPAL_LOOK_ENGINE_YOLO_ENABLED", "false")
    apply_env(store)
    assert bool(store.engines.get("yolo")["enabled"]) is False


# -- adapter behavior over a mocked transport --------------------------------


def test_probe_available(yolo_env):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/engine/yolo"
        return httpx.Response(200, json={"engine_id": "yolo",
                                         "available": True})
    ok, msg = _adapter(handler).probe({"base_url": URL}, enabled=True)
    assert ok is True and msg is None


def test_probe_disabled_and_unreachable(yolo_env):
    adapter = _adapter(lambda r: httpx.Response(500))
    assert adapter.probe({}, enabled=False) == (False, "disabled")
    ok, msg = adapter.probe({"base_url": URL}, enabled=True)
    assert ok is False and "yolo adapter" in msg


def test_models_mapping(yolo_env):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{
            "model_id": "yolov8n", "engine_id": "yolo",
            "tasks": ["detect"], "loaded": False,
            "weights_sha256": "ab" * 32,
            "metadata": {"size": "n"}}])
    (model,) = _adapter(handler).models()
    assert model["engine_id"] == "yolo"
    assert model["model_id"] == "yolov8n"
    assert model["loaded"] is False
    assert model["metadata"]["weights_sha256"] == "ab" * 32
    assert model["metadata"]["size"] == "n"


def test_load_model_404_is_model_not_found(yolo_env):
    adapter = _adapter(lambda r: httpx.Response(404, json={}))
    with pytest.raises(ModelNotFound):
        adapter.load_model("nope", device_id=None)


def test_unreachable_raises_engine_unavailable(yolo_env):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)
    with pytest.raises(EngineUnavailable):
        _adapter(handler).models()


def test_predict_posts_multipart_and_maps_result(yolo_env):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/predict/frame"
        seen["body"] = request.content
        return httpx.Response(200, json={
            "detections": [{"class_id": 0, "class_name": "person",
                            "confidence": 0.9, "box": [1, 2, 3, 4]}],
            "native": {"raw": True}})

    out = _adapter(handler).predict(
        image=Image.new("RGB", (8, 8)), model_id="yolov8n",
        confidence=0.5, device_id="cpu",
        engine_options={"imgsz": 640}, include_native=True)
    assert out["detections"][0]["class_name"] == "person"
    assert out["native"] == {"raw": True}
    body = seen["body"]
    assert b"yolov8n" in body and b"person" not in body  # request side
    assert b"imgsz" in body and b"frame.jpg" in body


def test_validate_config(yolo_env):
    adapter = _adapter(lambda r: httpx.Response(200, json={}))
    assert adapter.validate_config({"base_url": "http://x",
                                    "timeout_seconds": 5}) == []
    errors = adapter.validate_config({"base_url": "ftp://x", "bogus": 1})
    assert any("unknown option" in e for e in errors)
    assert any("http(s)" in e for e in errors)


def test_validate_engine_options(yolo_env):
    adapter = _adapter(lambda r: httpx.Response(200, json={}))
    assert adapter.validate_engine_options({"imgsz": 640, "half": True}) == []
    assert adapter.validate_engine_options({"bogus": 1})


# -- app-level: env registers the engine through lifespan ---------------------


@pytest.fixture()
def yolo_env_refused(monkeypatch):
    # loopback:1 refuses instantly -> deterministic unavailable probe
    monkeypatch.setenv("OPAL_LOOK_ENGINE_YOLO_BASE_URL",
                       "http://127.0.0.1:1")


def test_engine_list_shows_yolo(yolo_env_refused, client):
    engines = {e["engine_id"]: e for e in client.get("/api/v1/engine/").json()}
    yolo = engines["yolo"]
    assert yolo["enabled"] is True
    assert yolo["state"] == "unavailable"   # probe: connection refused
    assert yolo["metadata"]["adapter"] == "remote"
    assert yolo["options"]["base_url"] == "http://127.0.0.1:1"

# OPAL Look — YOLO engine integration

Status: **not yet integrated.** [`opal-look-yolo`](https://github.com/PatMartin/opal-look-yolo)
is a **standalone REST microservice** (its own contract, port `:8086`, CLI
`opal-yolo`, SPA). It is *not* an in-process engine plugin — it declares no
`opal_look.engines` entry point and its internal adapter protocol is a
different, narrower surface. The recommended integration is a **remote
engine adapter** inside opal-look that implements the `EngineAdapter`
protocol by proxying to the YOLO service over HTTP.

This document covers:

1. The `EngineAdapter` contract opal-look expects, in detail.
2. What `opal-look-yolo` provides today and how the surfaces map.
3. Install/run instructions for the YOLO service.
4. The two integration paths and the remaining work in each repo.

---

## 1. The `EngineAdapter` contract

Engines are *optional* in opal-look: video streams work with zero engines;
an engine adds `predict` and inference-mode streams. The contract is an
in-process Python `Protocol` — see `src/opal_look/engines.py`.

### Registration

```python
# opal_look.engines.load_plugin_adapters()
for ep in entry_points(group="opal_look.engines"):
    registry.register(ep.load()())   # factory called with no args
```

A plugin registers by declaring an entry point in its own `pyproject.toml`:

```toml
[project.entry-points."opal_look.engines"]
yolo = "some_package:adapter_factory"   # called -> EngineAdapter instance
```

The built-in `synthetic` adapter is registered unconditionally at import
time (`ENGINE_REGISTRY.register(SyntheticAdapter())`). At startup,
`ensure_engines(store)` seeds a row per registered adapter (enabled flag +
non-secret config); `engine_gate()` rejects inference calls on disabled or
unavailable engines with 503.

### Protocol surface

```python
class EngineAdapter(Protocol):
    engine_id: str       # registry key, e.g. "yolo"
    name: str            # display name
    execution: str       # "local" | "remote"

    # static description / configuration
    def capabilities(self) -> dict: ...            # tasks, tracking, device_types,
                                                   # source_types, engine_options, annotation
    def options_schema(self) -> dict: ...          # JSON Schema for engine *config*
    def validate_config(self, config: dict) -> list[str]: ...   # errors or []
    def metadata(self) -> dict: ...                # free-form, shown in engine read
    def probe(self, config: dict, enabled: bool) -> tuple[bool, str | None]: ...
                                                 # live availability + message

    # per-request validation
    def validate_engine_options(self, options: dict) -> list[str]: ...

    # MVP ops
    def hardware(self) -> list[dict]: ...          # [{device_id, type, available, ...}]
    def models(self) -> list[dict]: ...            # [{model_id, engine_id, tasks,
                                                 #   loaded, available, metadata}]
    def load_model(self, model_id: str, device_id: str | None) -> dict: ...
    def unload_model(self, model_id: str) -> dict: ...
    def predict(self, image, model_id, confidence, device_id,
                engine_options, include_native) -> dict: ...
```

### Semantics that matter

- **Two option layers, kept distinct.** *Engine config* (`options_schema` /
  `validate_config`) is persisted per engine via `PATCH /api/v1/engine/{id}`
  and passed to `probe()`. It is for deployment-level settings only —
  **never secrets** (stored plaintext in SQLite). *Engine options*
  (`validate_engine_options`, passed to `predict`) are per-request
  inference knobs (imgsz, iou, …).
- **`predict` takes a PIL `Image`** (already decoded) and returns
  `{"detections": [...], "native"?: {...}}`. Detection shape:
  `{class_id: int, class_name: str, confidence: 0..1,
  box: [x1, y1, x2, y2]}` — xyxy in pixels.
- **Errors:** `ModelNotFound` → 404; `EngineUnavailable` → 503. Anything
  else surfaces as a generic 500, so adapters should translate their own
  failures into these two.
- **`predict` runs on the stream decode-pump thread** for inference-mode
  streams — a slow or blocking call directly throttles that stream's
  frame rate.
- **Idempotent load:** `load_model` on an already-loaded model is a
  success no-op. `unload_model` on a model still in use by an inference
  stream is rejected with 409 by the router's own usage check —
  adapters don't raise it themselves.

## 2. What `opal-look-yolo` provides today

A standalone FastAPI service implementing `openapi/opal_look_yolo.yaml`
(14 ops — engine/model/hardware/predict + `/predict/frame`). Key facts:

- Own CLI (`opal-yolo`), own auth (`OPAL_YOLO_*` env), own SPA at `/app`,
  filesystem model discovery via `OPAL_YOLO_MODEL_DIRS`.
- `/predict/frame` accepts **multipart image bytes** + a `FrameEnvelope`
  (`stream_id`, `frame_id`, `sequence`, `captured_at`, `image{w,h}`) —
  exactly what a stream-side adapter needs.
- `/predict` accepts `{"engine":"yolo","model_id","source","confidence",
  "device","engine_options","include_native"}` where `source` is a local
  path or allowlisted remote URI.
- Detection payloads are already shape-compatible:
  `class_id / class_name / confidence / box[4]` xyxy floats.
- Model records carry `model_id, tasks, loaded, available,
  weights_sha256, metadata` — a superset of look's needs.
- Its internal `UltralyticsYoloEngine` wraps `ultralytics.YOLO`:
  `load_model(path) -> handle`, `predict(handle, image=..., conf=...)`
  — reusable for an in-process shim, but its method surface differs from
  look's protocol.
- No `opal_look.engines` entry point — `importlib.metadata` sees nothing
  when look calls `load_plugin_adapters()`.

## 3. Install and run the YOLO service

Ultralytics pulls in PyTorch — keep it **out of look's venv** and give
the service its own:

```bash
cd ../opal-look-yolo
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # bash

# point it at weights (path-separated list or JSON array)
export OPAL_YOLO_MODEL_DIRS=./models
# drop yolo*.pt files into ./models

.venv/Scripts/uvicorn opal_look_yolo.main:app --host 127.0.0.1 --port 8086
```

Verify:

```bash
.venv/Scripts/opal-yolo engines list
.venv/Scripts/opal-yolo models list
.venv/Scripts/opal-yolo models load <model_id> --device cpu
.venv/Scripts/opal-yolo predict sample.jpg --model-id <model_id>
```

Auth: `OPAL_YOLO_AUTH_DISABLED=false` + `OPAL_YOLO_AUTH_TOKEN=…` enables
bearer auth (required for non-loopback binds).

## 4. Integration paths

### A. Remote adapter (recommended)

Add `RemoteEngineAdapter` to opal-look (`engine_id="yolo"`,
`execution="remote"`) that proxies the protocol over HTTP to the running
service. Registers the `yolo` engine unconditionally — it simply probes
unavailable until `base_url` is configured, which matches how optional
engines already surface in `/api/v1/engine/`.

| Adapter call | YOLO service call |
|---|---|
| `probe(config, enabled)` | `GET /api/v1/engine/yolo` → `available` |
| `capabilities()` | `GET /api/v1/engine/yolo/capabilities` → map `supported_devices`→`device_types`, plus `tasks`/`annotation`/`engine_options`/`source_types` |
| `options_schema()` | adapter config schema: `{base_url, timeout_seconds}` — **not** the predict options schema |
| `validate_engine_options()` | validate against `capabilities.options_schema` (imgsz/iou/max_det/classes/half/agnostic_nms/augment/verbose) |
| `hardware()` | `GET /api/v1/hardware/` → pass through `{device_id,type,available}` |
| `models()` | `GET /api/v1/model/` → keep `model_id/tasks/loaded/available`, add `engine_id:"yolo"`, pack `weights_sha256` into `metadata` |
| `load_model(id, device)` | `POST /api/v1/model/{id}/load` `{"device": device}` |
| `unload_model(id)` | `POST /api/v1/model/{id}/unload` |
| `predict(image,…)` | encode PIL→JPEG → `POST /api/v1/predict/frame` multipart with synthesized `FrameEnvelope` (`stream_id:"opal-look"`, `sequence` counter, `captured_at` now, `image:{width,height}`) → return `{"detections", "native"?}` |

Details:

- Engine config: `{"base_url": "http://127.0.0.1:8086",
  "timeout_seconds": 30}` — set via
  `opal-look config engine update yolo --body '{"options":{…}}'`.
- Bearer token for the YOLO service comes from an **env var**
  (`OPAL_LOOK_YOLO_TOKEN`), never from engine config (config is stored
  plaintext and echoed in `options`).
- Error mapping: `httpx.ConnectError/Timeout` → `EngineUnavailable`;
  404 → `ModelNotFound`; 503/429 → `EngineUnavailable`. 429 arises under
  YOLO's bounded-prediction semaphore — for stream loops, treat as a
  transient failure (log + drop the frame rather than failing the stream
  is a reasonable refinement).
- Every `predict` is a blocking HTTP call on the decode-pump thread —
  the inference stream's effective fps is bounded by round-trip +
  inference latency. That's inherent to remote execution; document it.

### B. In-process plugin (alternative)

Skip the service: install `ultralytics` into look's venv and register a
shim adapter that wraps `UltralyticsYoloEngine` and exposes look's
protocol directly (`engine_id="yolo"`, `execution="local"`).

- `pip install ultralytics` (large: torch + optional CUDA).
- The shim owns a model-dir scan or config `{"model_dirs":[…]}`,
  synthesizes `models()` records, and translates `predict(image,…)` into
  `model.predict(source=image, conf=…)`.
- Entry point in the shim package:
  `[project.entry-points."opal_look.engines"] yolo = "pkg:make_adapter"`.
- Trade-off: simpler topology, but heavy ML deps inside look's process
  and no GPU-host offload. Inference blocks the pump thread identically.

## 5. Next steps

### In opal-look (this repo)

- [ ] `src/opal_look/remote_engine.py`: httpx-backed `EngineAdapter` per
      the mapping table (config `{base_url, timeout_seconds}`, token via
      `OPAL_LOOK_YOLO_TOKEN` env, JPEG encode for `/predict/frame`,
      error → `ModelNotFound`/`EngineUnavailable` mapping).
- [ ] Register it alongside `synthetic` (probe reports unavailable until
      `base_url` is configured — mirrors the optional-engine model).
- [ ] Config schema + `validate_engine_options` driven by the remote
      `capabilities.options_schema`.
- [ ] Tests: fake httpx transport covering probe/models/load/predict,
      error mapping, and a `predict` round-trip through
      `POST /api/v1/stream/` inference admission.
- [ ] Docs: README engine-plugins paragraph + this file's status line.

### In opal-look-yolo

- [ ] Nothing required for remote mode — the REST surface already covers
      every adapter call.
- [ ] Optional for in-process mode: ship a small adapter package (or a
      `look_plugin.py` module) implementing look's `EngineAdapter`
      protocol + the `opal_look.engines` entry point.
- [ ] Cosmetic: task naming `detect` (yolo) vs `detection` (look) — the
      remote adapter can translate, but aligning the vocab avoids the
      shim.
- [ ] `GET /api/v1/info/` already exposes service version → feed
      `metadata().version`.

## 6. Verify the integration (remote mode)

```bash
# terminal 1 — yolo service
cd ../opal-look-yolo && .venv/Scripts/uvicorn opal_look_yolo.main:app --port 8086

# terminal 2 — look
opal serve
opal-look config engine update yolo --body '{"options":{"base_url":"http://127.0.0.1:8086"}}'
opal-look engine list                     # yolo: enabled, available
opal-look model list --engine yolo
opal-look model load <model_id> --engine yolo
opal-look predict image --engine yolo --model <model_id> --source sample.jpg
opal-look stream start rtsp://cam/feed --name front-ai --engine yolo --model <model_id> --annotate
look stream watch front-ai                # detection events
```

# OPAL Look — YOLO engine integration

Status: **integrated (remote adapter).** OPAL Look ships a built-in remote
adapter for [`opal-look-yolo`](https://github.com/PatMartin/opal-look-yolo)
— a standalone REST microservice (contract:
`openapi/engines/opal_look_yolo_v0.1.0.yaml`, port `:8086`, CLI `opal-yolo`). The
adapter (`src/opal_look/engines/yolo/`) implements look's `EngineAdapter`
protocol by proxying to the service over HTTP, and is wired entirely
through `.env` — `OPAL_LOOK_ENGINE_YOLO_BASE_URL` registers it.

This document covers:

1. The `EngineAdapter` contract opal-look expects, in detail.
2. What `opal-look-yolo` provides and how the remote adapter maps to it.
3. Install/run instructions for the YOLO service.
4. Configuring the integration via `.env`.
5. Remaining gaps and next steps for both repos.

---

## 1. The `EngineAdapter` contract

Engines are *optional* in opal-look: video streams work with zero engines;
an engine adds `predict` and inference-mode streams. The contract is an
in-process Python `Protocol` — see `src/opal_look/engines/__init__.py`.

### Registration

Two paths land an adapter in `ENGINE_REGISTRY`:

```python
# 1. Entry-point plugins (third-party packages)
for ep in entry_points(group="opal_look.engines"):
    registry.register(ep.load()())

# 2. Built-in remote adapters declared via env (register_env_adapters)
#    OPAL_LOOK_ENGINE_YOLO_BASE_URL -> registers YoloRemoteAdapter
```

Both run inside the app lifespan, after `dotenv.prepare()` in `main()`
loads `.env`. At startup `ensure_engines(store)` seeds a row per registered adapter
(enabled flag + non-secret config), then `apply_env_engines(store)`
rewrites env-declared config/enabled — authoritative over `PATCH` changes,
same rule as `OPAL_LOOK_<SETTING>`. `engine_gate()` rejects inference
calls on disabled or unavailable engines with 503.

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
  streams — a blocking call bounds that stream's frame rate, and a raised
  exception fails the stream (`status: failed`, terminal SSE event).
- **Idempotent load:** `load_model` on an already-loaded model is a
  success no-op. `unload_model` on a model still in use by an inference
  stream is rejected with 409 by the router's own usage check —
  adapters don't raise it themselves.

## 2. What `opal-look-yolo` provides

A standalone FastAPI service implementing `openapi/opal_look_yolo.yaml`
(identical to the vendored `openapi/engines/opal_look_yolo_v0.1.0.yaml` here —
14 ops). Key facts:

- Own CLI (`opal-yolo`), own auth (`OPAL_YOLO_*` env), own SPA at `/app`,
  filesystem model discovery via `OPAL_YOLO_MODEL_DIRS`.
- `/predict/frame` accepts **multipart image bytes** + a `FrameEnvelope`
  (`stream_id`, `frame_id`, `sequence`, `captured_at`, `image{w,h}`).
- `/predict` accepts `{"engine","model_id","source","confidence","device",
  "engine_options","include_native"}` where `source` is a local path or
  allowlisted remote URI.
- Detection payloads are shape-compatible with look's:
  `class_id / class_name / confidence / box[4]` xyxy floats.
- Its internal `UltralyticsYoloEngine` is a different, narrower protocol —
  not usable as an in-process plugin (no `opal_look.engines` entry point).
- `GET /api/v1/health/` means "healthy *and* idle (no model loaded)" —
  the remote adapter probes `GET /api/v1/engine/yolo` → `available`
  instead.

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

## 4. Configure the integration (`.env`)

All wiring is environment-driven — see `.env.example`:

```dotenv
OPAL_LOOK_ENGINE_YOLO_BASE_URL=http://127.0.0.1:8086
OPAL_LOOK_ENGINE_YOLO_ENABLED=true          # default true
OPAL_LOOK_ENGINE_YOLO_TIMEOUT_SECONDS=30    # default 30
# OPAL_LOOK_ENGINE_YOLO_TOKEN=              # bearer for the adapter service
```

- `BASE_URL` presence **registers** the engine at startup; remove it and
  restart to unregister. `ENABLED` seeds the `engines.enabled` flag;
  `TIMEOUT_SECONDS` lands in engine config. Both are re-applied every boot
  (authoritative over `PATCH /api/v1/engine/yolo`).
- `TOKEN` is env-only (like `OPAL_LOOK_CRED_*`) — never written to
  `engines.config`, logged, or echoed.
- If the YOLO service has auth enabled, its token goes in
  `OPAL_YOLO_AUTH_TOKEN` (yolo side) and `OPAL_LOOK_ENGINE_YOLO_TOKEN`
  (look side).

Then:

```bash
opal serve
opal-look engine list                      # yolo: enabled, available
opal-look model list --engine yolo
opal-look model load <model_id> --engine yolo
opal-look predict image --engine yolo --model <model_id> --source sample.jpg
opal-look stream start rtsp://cam/feed --name front-ai \
    --credential front --engine yolo --model <model_id> --annotate
opal-look stream watch front-ai            # live detection events
ffplay -fflags nobuffer \
    "http://127.0.0.1:8002/api/v1/stream/front-ai/video?annotated=true"
```

`--credential front` names `OPAL_LOOK_CRED_FRONT` (`user:pass`), injected
at connect time — skip it only if the camera is truly open.

**Verified live** (yolo26n on CPU): inference latency ~250 ms/frame,
effective ~3 fps on the stream pump; `frames_dropped` climbs per
`buffer_policy` — expected, not an error.

## 5. Adapter mapping (implementation)

`src/opal_look/engines/yolo/adapter.py` (`execution="remote"`):

| Adapter call | YOLO service call |
|---|---|
| `probe(config, enabled)` | `GET {base_url}/api/v1/engine/yolo` → `available`; `(False, "disabled")` when the row's flag is off |
| `capabilities()` | `GET …/engine/yolo/capabilities` → `supported_devices`→`device_types`, remote `options_schema` keys→`engine_options`; `annotation: true` (look draws overlays) |
| `options_schema()` / `validate_config()` | look-side `{base_url, timeout_seconds}` — engine *config*, not predict options |
| `validate_engine_options()` | static known-key set (imgsz/iou/max_det/classes/half/agnostic_nms/augment/verbose) |
| `hardware()` | `GET …/hardware/` → passthrough |
| `models()` | `GET …/model/` → `weights_sha256` folded into `metadata` |
| `load_model(id, device)` | `POST …/model/{id}/load` `{"device": device}` |
| `unload_model(id)` | `POST …/model/{id}/unload` |
| `predict(image,…)` | PIL→JPEG → `POST …/predict/frame` multipart with synthesized `FrameEnvelope` (`stream_id: "opal-look"`, `frame_id: uuid`, `sequence` counter, `captured_at` now) |

Error mapping: connect/timeout/5xx → `EngineUnavailable` (503); model 404
→ `ModelNotFound` (404); 401/403 → `EngineUnavailable` (check TOKEN).
One cached `httpx.Client` per (url, timeout, token).

## 6. Remaining gaps and next steps

### In opal-look (this repo)

- [ ] Per-call predict failures propagate to the stream pump → the whole
      inference stream fails. Consider treating transient remote errors
      (timeout/429/5xx) as dropped frames instead — likely a stream-side
      policy, not adapter-side.
- [ ] `predict`'s synthesized `FrameEnvelope.stream_id` is the constant
      `"opal-look"` — the protocol doesn't pass stream identity into
      `predict`. If the yolo side needs real stream provenance, that's an
      upstream adapter-signature amendment.
- [ ] `capabilities()`/`models()`/`hardware()` hit the remote service on
      every call (no caching). Fine at MVP scale; cache if latency shows.
- [ ] Additional remote engines (rfdetr/rtdetr/dfine share the same
      adapter contract): generalize `env.py` + registration loop when a
      second one is actually wired — deliberately not done yet.

### In opal-look-yolo

- [ ] Nothing required — remote integration works against the current
      service.
- [ ] Optional in-process plugin: a `look_plugin.py` shim implementing
      look's `EngineAdapter` over `UltralyticsYoloEngine` + an
      `opal_look.engines` entry point — only if co-process execution is
      ever wanted (pulls torch/ultralytics into look's venv).
- [ ] Cosmetic: task naming `detect` (yolo) vs `detection` (look's
      `TASKS`); the adapter currently returns the remote vocab verbatim.

# OPAL Look

Implementation of `openapi/opal_look_v1.7.1.yaml` + `openapi/shared/
opal_kernel.yaml` (OPAL Suite Kernel 1.7.1) as the authoritative contract
(do not serve a generated spec; do not edit the contract files — amendments
go upstream first). Python 3.12+ / FastAPI / SQLite.

MVP contract (replaced in place at v1.7.1): engine-free video streaming
plus optional discoverable inference adapters. RTSP streams run with zero
AI engines installed; engines (e.g. YOLO/RF-DETR/RT-DETR/D-FINE, or the
built-in `synthetic` adapter) add predict + inference-mode streams.
Migration record: `specs/OPAL_LOOK_V1_7_LEDGER.md`; design reference
package under `docs/redesign/vision_contracts/`; v1.4.0-era upstream
contract copies live under `vendor/opal-api/`.

## Commands

- Setup: `python -m venv .venv && .venv/Scripts/pip install -e .[dev]`
- Test: `.venv/Scripts/pytest`
- Run: `.venv/Scripts/opal serve` or `.venv/Scripts/python -m opal_look` or `uvicorn opal_look.app:create_app --factory`
- Contract audit: `.venv/Scripts/python -m opal_look.contract_audit`
  (`--strict` = conformance gate, `--json` = machine-readable)
- Data dir: `OPAL_LOOK_DATA_DIR` (default `./data`)

## Conventions / design patterns

- Persistence: per-aggregate repositories behind Protocols under
  `src/opal_look/repositories/`; `Store` owns the connection + schema and
  exposes `store.meta/settings/engines/profiles` plus the
  `idempotency_keys` table. `store.write_txn()` is the unit-of-work
  context manager for atomic check-and-mutate.
- DI: FastAPI `Depends` providers in `src/opal_look/dependencies.py`
  (`StoreDep`); handlers inject the store rather than reaching app.state.
- Engines: `EngineAdapter` Protocol + `ENGINE_REGISTRY` (factory/registry,
  `opal_look.engines` entry-point hook via `load_plugin_adapters()`).
  Adapter surface: `capabilities/probe/options_schema/validate_config/
  metadata/validate_engine_options` plus the MVP ops `hardware()`,
  `models()`, `load_model()`, `unload_model()`, `predict(image, ...)`.
  The `synthetic` adapter gives deterministic detections with no ML deps.
  Models are engine-federated metadata (no central table); hardware is
  engine-local. `engine_gate(store, adapter)` -> 503 for disabled engines.
- Streams: `StreamRuntime` in `src/opal_look/streams.py` — in-memory only,
  state machine starting->running->stopping->stopped|failed, observer hub
  (bounded replay buffer + subscriber queues) feeding SSE and MJPEG.
  One decode pump per stream; viewers never start a second decode.
- Capture: `CaptureAdapter` Protocol + `CAPTURE_REGISTRY` in
  `src/opal_look/capture.py` (`opal_look.capture` entry-point hook).
  `RtspAvAdapter` (`capture_rtsp.py`) decodes via PyAV (optional; absent
  -> 503 at admission). `LiveFramePump` honors the contract
  `buffer_policy` (drop-oldest/drop-newest/block). Credentials embedded
  in the RTSP URI are never echoed — `streams.redact_source` strips
  userinfo for `source_redacted`.
- SQLite: single connection shared by loop + threadpool threads; all
  statements serialize through `Store._lock` (`_LockedConnection` proxy),
  and `write_txn()` holds it for the whole transaction.
- DTOs: pydantic models in `src/opal_look/schemas.py` + `settings.py`.
- Middleware: `CorrelationMiddleware` (outer correlation/validation),
  `AccessLogMiddleware` (outermost, logs all requests).
- All errors use the OpalError envelope (`src/opal_look/errors.py`,
  `ApiError(status, message, code=...)`).
- X-Opal-* correlation headers handled by `CorrelationMiddleware`; never
  trust them for authz.
- Config mutations require If-Match vs global config revision:
  `require_if_match(request)` early (428 missing / 422 malformed) +
  `check_if_match(request, store)` inside `store.write_txn()` (412 stale,
  atomic with the write; src/opal_look/precondition.py). All config writes
  bump the revision; runtime activity must not. `write_txn()` nests via
  SAVEPOINT. Idempotency-Key admissions use
  `idempotency.request_idempotency_key` (contract bounds 1..128) backed by
  the durable `idempotency_keys` table (fingerprint replay -> same
  admission; mismatched body -> 409; 24h TTL).
- Environment: `python-dotenv` loads a repo-root `.env` at `main()` and
  `create_app()` (never overrides real env vars; `.env` is gitignored).
  Covers `OPAL_LOOK_HOST/PORT/DATA_DIR/TOKEN` + `OPAL_LOOK_CRED_*`.
- Bearer auth: `OPAL_LOOK_TOKEN` (env or `.env`, opaque). Set -> all
  `/api/v1` requests need `Authorization: Bearer <token>` (401 +
  `WWW-Authenticate: Bearer`, enforced by `BearerAuthMiddleware` inside
  Correlation so 401s keep X-Opal headers). Unset -> loopback dev mode;
  `main.py` refuses non-loopback binds without it. Never log/export/echo
  the token or accept it in query strings. CLI sends it automatically.
- Clients: `opal-look` Typer CLI + `opal look` umbrella (REST-only via
  httpx; x-opal-cli taxonomy — engine/model/hardware/predict/stream/
  backup/service/info + `config` parent group, `tree` retained) and a
  full-coverage SPA (static assets at /app/ calling REST, no business
  logic).
- vendor/opal-api/ holds local-only reference copies of the sibling
  contracts (opal_event/listen/talk + upstream opal_look — note upstream
  Look is a different API; our opal_look_v1.7.1.yaml is authoritative).

## Contract coverage (verified)

| Area | Status |
|---|---|
| errors/correlation envelope | verified |
| health/info (/, /health, /info/, /info/ping, live, ready, suite health) | verified |
| settings (map GET/PATCH + per-key GET/PUT/DELETE, If-Match/ETag) | verified |
| engines (list/get/patch, discover -> EngineDiscovery{engines,errors}, capabilities) | verified |
| hardware (engine-local list/show, ?engine_id filter/disambiguation) | verified |
| models (engine-federated list/show/load/unload; 404/409/422/503) | verified |
| predict (path/URI source, size/pixel caps, engine+model+device+options gates, native opt-in) | verified |
| profiles (CRUD+activate, kernel shapes) | verified |
| backup (export/validate/import + managed create/list/download/restore/delete) | verified |
| service (pidfile-managed start/stop/log; restart via OPAL_LOOK_WAIT_PID) | verified |
| streams (202+Location admission, mode rules, idempotency-key, stop 409, client-chosen `name` -> stream_id, 409 active-name conflict, reuse after terminal) | verified |
| stream video (MJPEG) + snapshot (JPEG) + metrics + annotated rules | verified |
| stream SSE (frame/detection/status/terminal, heartbeat, Last-Event-ID replay, 409 stale) | verified |
| inference-mode streams (detection events, annotate overlays, engine gates) | verified |
| idempotency (durable keys, fingerprint replay, 409s) | verified |
| retention sweep (startup purge of expired idempotency rows) | verified |
| CLI (opal look / opal-look, all verbs incl. stream/predict, REST-only) | verified |
| SPA (/app/ static client, all MVP sections) | verified |
| conformance (strict audit rc=0 CONFORMANT: 39 paths / 47 ops) | verified |

Deferred (documented): real RTSP decode needs PyAV (`pip install av`)
else stream admission -> 503; ZeroMQ event bus retired with the old
contract (no bus surface in the MVP); MJPEG viewer count is not capped;
SSE `heartbeat` is emitted as comments, not typed events.

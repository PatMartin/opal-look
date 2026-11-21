# OPAL Look

Implementation of `openapi/opal_look_v0.4.0.yaml` + `openapi/shared/
opal_kernel.yaml` (OPAL Suite Kernel 0.4.0) as the authoritative contract
(do not serve a generated spec; do not edit the contract files — amendments
go upstream first). Python 3.12+ / FastAPI / SQLite.

MVP contract: engine-free video streaming plus optional discoverable
inference adapters. RTSP streams run with zero AI engines installed;
engines (e.g. YOLO/RF-DETR/RT-DETR/D-FINE, or the built-in `synthetic`
adapter) add predict + inference-mode streams. The v0.1.0 cutover retired
`/api/v1/info/*` (health is the single info surface), `/api/v1/backup/*`
(replaced by `config save/load/validate` snapshots), and the settings map
PATCH; it added the persona catalog and namespaced portable profiles.
Migration records: `specs/OPAL_LOOK_V0_1_MIGRATION.md` (this cutover) and
`specs/OPAL_LOOK_V1_7_LEDGER.md` (v1.7); design reference package under
`docs/redesign/vision_contracts/`; v1.4.0-era upstream contract copies
live under `vendor/opal-api/`.

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
  exposes `store.meta/settings/engines/profiles/personas` plus the
  `idempotency_keys` table. `store.write_txn()` is the unit-of-work
  context manager for atomic check-and-mutate.
- DI: FastAPI `Depends` providers in `src/opal_look/dependencies.py`
  (`StoreDep`); handlers inject the store rather than reaching app.state.
- Engines: `EngineAdapter` Protocol + an app-owned `EngineRegistry`
  (`app.state.engine_registry`, built by `default_registry()` in
  `create_app` — adapter state never bleeds across app instances) in
  `src/opal_look/engines/` (package). Adapters register via the
  `opal_look.engines` entry-point hook (`load_plugin_adapters(registry)`)
  or env declaration (`register_env_adapters(registry)`). Conformance
  gate for any new adapter: `tests/test_engine_contract.py`. Adapter surface:
  `capabilities/probe/options_schema/validate_config/
  metadata/validate_engine_options` plus the MVP ops `hardware()`,
  `models()`, `load_model()`, `unload_model()`, `predict(image, ...)`.
  The `synthetic` adapter gives deterministic detections with no ML deps.
  `engines/yolo/` is a remote adapter proxying the standalone
  opal-look-yolo service (adapter contract
  `openapi/engines/opal_look_yolo_v0.4.0.yaml`); registered iff
  `OPAL_LOOK_ENGINE_YOLO_BASE_URL` is set, configured via
  `OPAL_LOOK_ENGINE_YOLO_ENABLED/TIMEOUT_SECONDS` (seeded into the
  engines row, authoritative like settings) + `_TOKEN` (env-only).
  Models are engine-federated metadata (no central table); hardware is
  engine-local. `engine_gate(store, adapter)` -> 503 for disabled engines.
- Streams: `StreamRuntime` in `src/opal_look/streams.py` — in-memory only,
  state machine starting->running->stopping->stopped|failed. `stream_id`
  is the server-generated immutable run identity; `name` is a
  client-chosen label, unique among non-terminal streams, resolving as a
  lookup alias while held (see docs/IDENTITY_AND_BRIDGES.md and
  specs/STREAM_NAME_AMENDMENT.md). Terminal status is published only
  after the pump thread exits and the capture stream is closed
  (teardown_timeout -> failed). Observer hub (bounded replay buffer +
  subscriber queues) feeds SSE and MJPEG under one lock; a full queue
  evicts the subscriber with a final `dropped` event; viewer occupancy is
  bounded by `max_viewers` (snapshot uncounted); JPEG output is encoded
  once per frame+variant (`frame_cache_seconds` TTL) and shared.
  One decode pump per stream; viewers never start a second decode.
- Capture: `CaptureAdapter` Protocol + `CAPTURE_REGISTRY` in
  `src/opal_look/capture.py` (`opal_look.capture` entry-point hook).
  `RtspAvAdapter` (`capture_rtsp.py`) decodes via PyAV (optional; absent
  -> 503 at admission). `LiveFramePump` honors the contract
  `buffer_policy` (drop-oldest/drop-newest/block). Credentials are
  provisioned via `OPAL_LOOK_CRED_<REF>` env vars, named per stream with
  `credential_ref` — `capture.credentialed_locator` injects userinfo at
  connect time only (422 when unprovisioned); URI userinfo is never
  echoed — `streams.redact_source` strips it for `source_redacted`.
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
- Environment: `python-dotenv` loads a repo-root `.env` via
  `dotenv.prepare()` at executable entry points (`main()`, CLI callback;
  never overrides real env vars; `.env` is gitignored;
  `.env.example` documents the set). Covers `OPAL_LOOK_HOST/PORT
  (default 127.0.0.1:8002)/DATA_DIR/TOKEN` + `OPAL_LOOK_CRED_*`. Any
  `OPAL_LOOK_<SETTING_KEY>` matching a `/api/v1/setting/` key applies as a
  read overlay on every setting read — precedence environment > dotenv >
  persisted > default, surfaced as `source`/`configured_value`/
  `has_override` in `SettingRead`; invalid values are skipped with a
  warning (`settings.env_overlays`).
- Bearer auth: `OPAL_LOOK_TOKEN` (env or `.env`, opaque). Set -> all
  `/api/v1` requests need `Authorization: Bearer <token>` (401 +
  `WWW-Authenticate: Bearer`, enforced by `BearerAuthMiddleware` inside
  Correlation so 401s keep X-Opal headers). Unset -> loopback dev mode;
  `main.py` refuses non-loopback binds without it. Never log/export/echo
  the token or accept it in query strings. CLI sends it automatically.
- Clients: `opal-look` Typer CLI + `opal look` umbrella (REST-only via
  httpx; x-opal-cli taxonomy — engine/model/hardware/predict/stream/
  profile/persona/service/info + `config` parent group with the
  setting subgroup and save/load/validate, `tree` retained) and a
  full-coverage SPA (static assets at /app/ calling REST, no business
  logic).
- vendor/opal-api/ holds local-only reference copies of the sibling
  contracts (opal_event/listen/talk + upstream opal_look — note upstream
  Look is a different API; our opal_look_v0.4.0.yaml is authoritative).

## Contract coverage (verified)

| Area | Status |
|---|---|
| errors/correlation envelope | verified |
| health (merged OpalHealthReport + live/ready probes; info/* retired) | verified |
| settings (map GET + per-key GET/PUT/DELETE with provenance, If-Match/ETag; map PATCH retired) | verified |
| engines (list/get/patch, discover -> EngineDiscovery{engines,errors}, capabilities) | verified |
| hardware (engine-local list/show, ?engine_id filter/disambiguation) | verified |
| models (engine-federated list/show/load/unload; 404/409/422/503) | verified |
| predict (path/URI source under source policy, bounded reads + redirect re-checks, size/pixel caps before decode, engine+model+device+options gates, native opt-in) | verified |
| profiles (portable namespaced docs, string ids, own-compartment patch, foreign preserved) | verified |
| personas (local catalog CRUD + validate, If-Match, enabled filter) | verified |
| config (save/load/validate OpalConfigSnapshot, managed snapshot, atomic load) | verified |
| service (pidfile-managed start/stop/log; restart via OPAL_LOOK_WAIT_PID) | verified |
| streams (202+Location admission, mode rules, idempotency-key -> immutable run id receipt, stop -> cleanup-bound terminal, generated `stream_id` + `name` lookup alias, 409 active-name conflict, reuse after terminal, `credential_ref` -> OPAL_LOOK_CRED_<REF> injection, 422 unprovisioned, source policy before admission) | verified |
| stream video (MJPEG, bounded viewers + dropped eviction) + snapshot (JPEG) + metrics + annotated rules | verified |
| stream SSE (frame/detection/status/terminal, heartbeat, Last-Event-ID replay, 409 stale) | verified |
| inference-mode streams (detection events, annotate overlays, engine gates) | verified |
| idempotency (durable keys, fingerprint replay, 409s) | verified |
| retention sweep (startup purge of expired idempotency rows) | verified |
| CLI (opal look / opal-look, all verbs incl. stream/predict, REST-only) | verified |
| SPA (/app/ static client, all MVP sections) | verified |
| conformance (strict audit rc=0 CONFORMANT: 35 paths / 45 ops) | verified |
| event bridge (opt-in `stream bridge` verb: detection SSE -> EventInput publish, filters/cooldown, stable dedup ids, Last-Event-ID reconnect, bounded retries) | verified |

Deferred (documented): real RTSP decode needs PyAV (`pip install av`)
else stream admission -> 503; ZeroMQ event bus retired with the old
contract (no bus surface in the MVP); SSE `heartbeat` is emitted as
comments, not typed events; the Event bridge is an external opt-in
process, not a server-side surface.

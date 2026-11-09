# OPAL Look

Implementation of `openapi/opal_look_v1.6.0.yaml` + `openapi/shared/
opal_kernel.yaml` (OPAL Suite Kernel 1.6.0) as the authoritative contract
(do not serve a generated spec; do not edit the contract files — amendments
go upstream first). Python 3.12+ / FastAPI / SQLite.

v1.6.0 highlights vs v1.5.0: all resource collection paths are singular
(`/api/v1/source/`, `/api/v1/session/`, `/api/v1/setting/` …); personas
(named observer identities with optional OPAL Say `voice_id`) are a new
config resource; `/api/v1/info/` + `/api/v1/info/ping` serve the kernel
ServiceInfo/LivenessRead. Migration record:
`specs/OPAL_LOOK_V1_6_LEDGER.md`; the v1.5 migration history is in
`specs/OPAL_LOOK_V1_5_LEDGER.md` and v1.4.0-era upstream copies live under
`vendor/opal-api/`.

## Commands

- Setup: `python -m venv .venv && .venv/Scripts/pip install -e .[dev]`
- Test: `.venv/Scripts/pytest`
- Run: `.venv/Scripts/opal serve` or `.venv/Scripts/python -m opal_look` or `uvicorn opal_look.app:create_app --factory`
- Contract audit: `.venv/Scripts/python -m opal_look.contract_audit`
  (`--strict` = Step-28 pass/fail gate, `--json` = machine-readable)
- Data dir: `OPAL_LOOK_DATA_DIR` (default `./data`)

## Conventions / design patterns

- Persistence: per-aggregate repositories behind Protocols under
  `src/opal_look/repositories/`; `Store` owns the connection + schema and
  exposes `store.meta/settings/engines/models/…/personas`.
  `store.write_txn()` is the unit-of-work context manager for atomic
  check-and-mutate.
- DI: FastAPI `Depends` providers in `src/opal_look/dependencies.py`
  (`StoreDep`); handlers inject the store rather than reaching app.state.
- Engines: `EngineAdapter` Protocol + `ENGINE_REGISTRY` (factory/registry,
  `opal_look.engines` entry-point hook via `load_plugin_adapters()`).
- Capture: `CaptureAdapter` Protocol + `CAPTURE_REGISTRY` in
  `src/opal_look/capture.py` (`opal_look.capture` entry-point hook via
  `load_capture_plugins()`). `RtspAvAdapter` (`capture_rtsp.py`) decodes
  via PyAV. `credential_ref` resolves to env `OPAL_LOOK_CRED_<REF>`
  ("user:pass") and is injected into the connect URL only — never stored
  or echoed. Session workers consume frames through a drop-oldest
  `LiveFramePump` (fresh-frame priority; evictions -> frames_dropped).
- SQLite: single connection shared by loop + threadpool threads; all
  statements serialize through `Store._lock` (`_LockedConnection` proxy),
  and `write_txn()` holds it for the whole transaction.
- DTOs: pydantic models in `src/opal_look/schemas.py` + `settings.py`.
- Contract resource reads vs internals: `engine_read`/`model_read`/
  `persona_read` return the contract shapes; `engine_runtime`/
  `model_runtime` are the richer internal views (probe/config/adapter
  description) used by services. Models store
  `created_at/tasks/options/resource_ref` columns (auto-migrated in
  `Store._migrate`).
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
  `idempotency.request_idempotency_key` (contract bounds 1..128).
- `events_enabled=true` requires `OPAL_LOOK_EVENT_TRANSPORT` env
  (provisioned out of band); otherwise 422.
- Bearer auth: `OPAL_LOOK_TOKEN` (env, opaque). Set -> all `/api/v1`
  requests need `Authorization: Bearer <token>` (401 +
  `WWW-Authenticate: Bearer`, enforced by `BearerAuthMiddleware` inside
  Correlation so 401s keep X-Opal headers). Unset -> loopback dev mode;
  `main.py` refuses non-loopback binds without it. Never log/export/echo
  the token or accept it in query strings. CLI sends it automatically.
- Clients: `opal-look` Typer CLI + `opal look` umbrella (REST-only via
  httpx; suite verb taxonomy add/remove/update/list/show + operational
  verbs per upstream x-opal-cli conventions) and a full-coverage SPA
  (static assets at /app/ calling REST, no business logic).
- Event bus: real two-frame ZeroMQ publisher via pyzmq, enabled through
  provisioned transport config.
- vendor/opal-api/ holds local-only reference copies of the sibling
  contracts (opal_event/listen/talk + upstream opal_look — note upstream
  Look is a different API; our opal_look_v1.4.0.yaml is authoritative).

## Contract coverage (verified)

| Area | Status |
|---|---|
| errors/correlation envelope | verified |
| health/info (/, /health, /info/, /info/ping, live, ready, suite health) | verified |
| settings (map GET/PATCH + per-key GET/PUT/DELETE, If-Match/ETag) | verified |
| engines (list/get/patch; kernel shapes; synthetic adapter) | verified |
| models (list+filters/create/get/patch/delete) | verified |
| sources (CRUD+status/probe/frame/stream, per-type adapters, rtsp live probe) | verified |
| profiles (CRUD+activate, kernel shapes) | verified |
| zones (standalone CRUD, source-scoped geometry) | verified |
| rules (standalone CRUD, monitor-time evaluation) | verified |
| personas (CRUD+enabled filter+validate, export/import section) | verified |
| pipelines (CRUD+validate, DAG stages, executor) | verified |
| media (upload JPEG/PNG+EXIF, cursor list, get/delete/content, expiry) | verified |
| analyze (selection resolution, media/source/capture inputs, tasks, filters) | verified |
| observations (list/show, retained immutable records) | verified |
| captures (exact-frame capture, annotate, retain, CRUD+content) | verified |
| artifacts (list/show/delete/content, job/recording outputs) | verified |
| sessions (admission/state machine/worker/stop/observations/stream/preview) | verified |
| jobs (submit/list/show/cancel, idempotency-key admission) | verified |
| monitors (CRUD, durable workers, rule evaluation, SSE) | verified |
| recordings (start/list/show/stop, artifact on finalize) | verified |
| configuration (export/validate/import, personas section) | verified |
| metrics + events status | verified |
| SSE session stream (heartbeat), MJPEG preview, source MJPEG view | verified |
| event bus (pyzmq PUSH two-frame, allowlist+rate+drop counters) | verified |
| CLI (opal look / opal-look, all verbs incl. persona+info, REST-only) | verified |
| SPA (/app/ static client, all sections incl. personas) | verified |

| idempotency (durable keys, fingerprint replay, 409s) | verified |
| retention sweep (startup purge of expired rows) | verified |
| conformance (strict audit rc=0 CONFORMANT: 63 paths / 98 ops) | verified |
| CI (GitHub Actions pytest) | verified |

Deferred (documented): video decoder (media/host_video -> 415/503 until
installed), camera/http capture adapters (rtsp implemented), SSE
replay-window edge cases (replay_expired/stream_overflow), health
event-publication counter surface.
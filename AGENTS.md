# OPAL Look

Implementation of the `opal_look_v1.4.0.yaml` OpenAPI contract (authoritative
interface; do not serve a generated spec). Python 3.12+ / FastAPI / SQLite.

**Migration in progress:** branch `feature/opal-look-1.5` targets the pinned
`opal_look_v1.5.0.yaml` (breaking revision; see
`specs/OPAL_LOOK_V1_5_MIGRATION.md` + `OPAL_LOOK_V1_5_LEDGER.md`). v1.4.0 YAML
stays as historical reference — do not edit either contract file.

## Commands

- Setup: `python -m venv .venv && .venv/Scripts/pip install -e .[dev]`
- Test: `.venv/Scripts/pytest`
- Run: `.venv/Scripts/opal-look` or `uvicorn opal_look.app:create_app --factory`
- Contract audit: `.venv/Scripts/python -m opal_look.contract_audit`
  (`--strict` = Step-28 pass/fail gate, `--json` = machine-readable)
- Data dir: `OPAL_LOOK_DATA_DIR` (default `./data`)

## Conventions / design patterns

- Persistence: per-aggregate repositories behind Protocols under
  `src/opal_look/repositories/`; `Store` owns the connection + schema and
  exposes `store.meta/settings/engines/models`. `store.write_txn()` is the
  unit-of-work context manager for atomic check-and-mutate.
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
- Planned clients (later phases): `opal-look-cli` (Typer, REST-only via
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
| health (/, /health, live, ready, suite health) | verified |
| settings (map GET/PATCH + per-key GET/PUT/DELETE, If-Match/ETag) | verified |
| engines (list/get/patch/validate; synthetic adapter) | verified |
| models (list+filters/create/get/patch/delete/validate) | verified |
| sources (CRUD+validate, per-type locator/option adapters, rtsp live probe) | verified |
| profiles (CRUD+activate+validate, resolved settings) | verified |
| devices/cameras (empty discovery; no adapters yet) | verified |
| media (upload JPEG/PNG+EXIF, cursor list, get/delete/content, expiry) | verified |
| analyze (selection resolution, media/source frame inputs, all 5 tasks, filters, persistence) | verified |
| results (search filters, cursor+budget, get/delete), ephemeral frame cache | verified |
| snapshots (exact-frame capture, annotate, retain, CRUD+content) | verified |
| sessions (admission/state machine/reconnect/worker/stop/delete/latest) | verified |
| SSE events stream (result+end events, heartbeat), MJPEG preview | verified |
| backup (export/import/validate + managed create/list/download/restore/delete) | verified |
| event bus (pyzmq PUSH two-frame, allowlist+rate+drop counters) | verified |
| CLI (opal-look-cli, all verbs, REST-only) | verified |
| SPA (/app/ static client, all sections) | verified |

| idempotency (durable keys, fingerprint replay, 409s) | verified |
| retention sweep (startup purge of expired rows) | verified |
| conformance (Spectral 0 errors; Schemathesis fixes applied) | verified |
| CI (GitHub Actions pytest) | verified |

Deferred (documented): video decoder (media/host_video -> 415/503 until
installed), camera/http capture adapters (rtsp implemented), SSE
replay-window edge cases (replay_expired/stream_overflow), health
event-publication counter surface.
# OPAL Look

Implementation of the `opal_look_v1.4.0.yaml` OpenAPI contract (authoritative
interface; do not serve a generated spec). Python 3.12+ / FastAPI / SQLite.

## Commands

- Setup: `python -m venv .venv && .venv/Scripts/pip install -e .[dev]`
- Test: `.venv/Scripts/pytest`
- Run: `.venv/Scripts/opal-look` or `uvicorn opal_look.app:create_app --factory`
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
- DTOs: pydantic models in `src/opal_look/schemas.py` + `settings.py`.
- Middleware: `CorrelationMiddleware` (outer correlation/validation),
  `AccessLogMiddleware` (outermost, logs all requests).
- All errors use the OpalError envelope (`src/opal_look/errors.py`,
  `ApiError(status, message, code=...)`).
- X-Opal-* correlation headers handled by `CorrelationMiddleware`; never
  trust them for authz.
- Config mutations require If-Match vs global config revision:
  `check_if_match(request, store)` inside `store.write_txn()`
  (src/opal_look/precondition.py). All config writes bump the revision.
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
| sources (CRUD+validate, per-type locator/option adapters) | verified |
| profiles (CRUD+activate+validate, resolved settings) | verified |
| devices/cameras (empty discovery; no adapters yet) | verified |
| media (upload JPEG/PNG+EXIF, cursor list, get/delete/content, expiry) | verified |
| analyze (selection resolution, media/source frame inputs, all 5 tasks, filters, persistence) | verified |
| results (search filters, cursor+budget, get/delete), ephemeral frame cache | verified |
| snapshots (exact-frame capture, annotate, retain, CRUD+content) | verified |
| sessions (admission/state machine/worker/stop/delete/latest; SSE+preview pending) | verified |
| SSE events stream, MJPEG preview | not started |
| backup | not started |
| event bus | deferred |

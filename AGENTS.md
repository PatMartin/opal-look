# OPAL Look

Implementation of the `opal_look_v1.4.0.yaml` OpenAPI contract (authoritative
interface; do not serve a generated spec). Python 3.12+ / FastAPI / SQLite.

## Commands

- Setup: `python -m venv .venv && .venv/Scripts/pip install -e .[dev]`
- Test: `.venv/Scripts/pytest`
- Run: `.venv/Scripts/opal-look` or `uvicorn opal_look.app:create_app --factory`
- Data dir: `OPAL_LOOK_DATA_DIR` (default `./data`)

## Conventions

- All errors use the OpalError envelope (`src/opal_look/errors.py`,
  `ApiError(status, message, code=...)`).
- X-Opal-* correlation headers handled by `CorrelationMiddleware`; never
  trust them for authz.
- Config mutations require If-Match vs global config revision (Step 2+).

## Contract coverage (verified)

| Area | Status |
|---|---|
| errors/correlation envelope | verified |
| health (/, /health, live, ready, suite health) | verified |
| settings | not started |
| engines/models/sources/profiles/devices | not started |
| media | not started |
| analyze | not started |
| sessions/SSE/preview | not started |
| results/snapshots | not started |
| backup | not started |
| event bus | deferred |

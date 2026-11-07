# OPAL-LOOK v1.5.0 Migration Ledger

Living record of the v1.4.0 → v1.5.0 migration on `feature/opal-look-1.5`.
Update the coverage line after every step commit. The numbers below come from
the tools, not estimates — see "How to reproduce".

---

## Upstream v1.5.0 re-target (steps U01+, spec `openapi/`)

The upstream `openapi/opal_look_v1.5.0.yaml` + `openapi/shared/opal_kernel.yaml`
(OPAL Suite Kernel 1.2.0) is now the authoritative contract, superseding the
local "Simplified" draft below. Upstream keeps sessions, profiles, rules,
zones, captures and artifacts as resources; suite-standard surfaces (engines,
profiles, settings, configuration, health) arrive via kernel `pathItems`.

### Upstream pinned inputs

- Contract: `openapi/opal_look_v1.5.0.yaml` SHA-256
  `71b785e340be7534b0bfdd901ce0d4ee251bcf90922de189a206dcdec3877247`.
- Kernel: `openapi/shared/opal_kernel.yaml` (v1.2.0) SHA-256
  `53ee85eaa6c1d3db52940c6aca6c2fc61ba380565cd41073a971e4a87848331d`.
  Do not edit either; amendments go upstream first.
- Step prompts: `specs/OPAL_LOOK_UPSTREAM_V1_5_IMPLEMENTATION_PROMPTS.md`.
- Audit tool resolves external `./shared/*` `$ref`s (pathItems + components).

### Upstream baseline (Step U01)

| Measure | Value |
|---|---|
| Contract inventory | 58 paths / 90 operations |
| Implemented routes | 64 ops |
| Covered | **58/90** |
| Missing | **32/90** — profiles (6), zones (5), rules (5), sessions (7), captures (5), artifacts (4) |
| Legacy-only `/api/v1` ops | 4 — `media/{id}/content`, `monitors/{id}/observations/stream`, `sources/{id}/capture`, `sources/{id}/observations/stream` |
| Contract structural problems | 0 |

### Upstream step log

| Step | Commit | Covered /90 | Notes |
|---|---|---|---|
| U01 pin+audit retarget | b128a48 | 58 | openapi/ committed, audit resolves external $refs, draft dup deleted |
| U02 engines+health kernel | bbcdbd0 | 58 | OpalEngine/OpalHealthReport/OpalHealthProbe shapes; CONTRACT_VERSION 1.5.0; dead engine-validate handler removed; stale-test floor 43→39 |
| U03 settings+config kernel | 56dadec | 58 |
| U04 profiles CRUD+activate | da0f1df | 64 | kernel OpalProfile via data-blob column; single-active invariant; active_profile_id wired into health; export/import roundtrip; stale profile test retired; floor 37 |
| U05 sources reconcile | 1abf77f | 64 | Source: zones dropped, capabilities added, state enum aligned (disconnected); kind remap http->http_mjpeg/camera->usb/image->file migrated; stale validate/devices/zones tests retired |
| U06 zones standalone | 969a80f | 69 | zones table+repo+router (list w/ source_id filter, create, show, patch, delete); embedded-zones harvest migration; monitor zone-eval reads zones table; export/import + validation wiring |
| U07 rules standalone | (this commit) | 74 | rules table+repo+router; kind enum + zone-ownership validation; last_triggered_at read-only; export/import+validate wiring; eval wiring deferred to U13 | OpalSettingsMap/SettingRead/SettingUpdate (updated_at/default/is_default/pending_restart via new override column); OpalConfigExport/OpalValidationReport/OpalImportResult; import takes bare bundle (+legacy wrapper compat); float-hours poisoning fixed via strict validated _settings_apply — no unit conversion remains; floor 39→37 |

---

## Simplified-draft migration (steps 01–28, completed)

## Pinned inputs

- Contract: `opal_look_v1.5.0.yaml` (repo root, byte-for-byte copy of the
  OPAL-API v1.5.0 draft). SHA-256
  `b1c21e4ae435108ea302bdd0fa2a365d1e3b4a42f3d723b1cad7b513efdc6c2f`.
  Do not edit; amendments go to OPAL-API first.
- Historical reference: `opal_look_v1.4.0.yaml` — kept unchanged for diffing.
- Audit tool: `python -m opal_look.contract_audit` (or `opal-look-audit`).
  Nonblocking progress report by default; `--strict` fails on any missing or
  legacy-only `/api/v1` operation or contract structural problem (Step 28 gate).
  `--json` emits the machine-readable form used below.

## Baseline (Step 01, branch point a6d84fb → commit TBD)

| Measure | Value |
|---|---|
| Contract inventory | 42 paths / 62 operations / 68 schemas |
| Implemented routes | 66 operations (46 paths) |
| Contract ops already covered | **26/62** |
| Contract ops missing | **36/62** |
| Legacy-only `/api/v1` ops | 38 |
| Service surface outside `/api/v1` | `GET /`, `GET /health` (+`/app` static mount) |
| Contract structural problems | 0 (3.1.0, unique operationIds, x-opal-cli complete, all local `$ref`s resolve) |
| Baseline `pytest -q` | 267 passed / **1 failed** / 0 skipped |
| Baseline failure | `test_sessions.py::test_session_rtsp_drops_for_freshness` — timing-sensitive (relies on >1ms scheduling to evict frames); passes in isolation, flakes under the full suite. Pre-existing; not a v1.5 regression. |

## Feature ledger

### Working now (route+method match v1.5; payload conformance verified per-step)

- engines list/show/update; models CRUD
- sources CRUD (v1.4 shapes — zones/secret_ref/status/probe/frame/stream/capture pending Steps 05–06, 17)
- media list/upload/show/delete/content (v1.4 shapes — unified kind/origin/TTL pending Step 16)
- settings map+leaf GET/PATCH/PUT/DELETE with strong ETag/If-Match (portable-settings alignment Step 24)
- health show/live/ready

### Missing entirely (no route)

- capabilities (Step 04); source status/probe/frame/stream/observations-stream/capture (06, 13–15, 17)
- pipelines CRUD+validate (07–09); monitors CRUD+SSE (18–21)
- analyze `/api/v1/analyze/` + `/analyze/image` (10–11); observations list/show (12)
- jobs list/submit/show/cancel (22); recordings list/start/show/stop (23)
- configuration export/validate/import (24); metrics, events/status (25)

### Legacy-only (implemented under `/api/v1`, absent from v1.5.0 — removed/replaced by Step 28)

- `/backup/*` (replaced by `/configuration/*`), `/profiles/*`, `/results/*`,
  `/sessions/*` + session events/preview/stop, `/snapshots/*`,
  `/devices/cameras/`, `*/validate` on sources/engines/models/profiles,
  `POST /api/v1/analyze` (v1.5 path is `/api/v1/analyze/` trailing slash)

### Notes

- Route-level audit only: a "covered" op means path+method exist; request/
  response schema, error, ETag, security and redaction conformance are verified
  in the owning step, not here.
- `POST /api/v1/analyze` vs `POST /api/v1/analyze/` is an honest miss: trailing
  slash matters in this contract.
- `x-opal-cli` shortcuts (`view`, `analyze`) exist in the contract metadata;
  CLI mirror is Step 26, SPA mirror Step 27.

## How to reproduce

```bash
.venv/Scripts/python -m pytest -q                 # full suite
.venv/Scripts/python -m opal_look.contract_audit  # progress report
.venv/Scripts/python -m opal_look.contract_audit --strict   # Step-28 gate
.venv/Scripts/python -m opal_look.contract_audit --json     # machine-readable
```

## Step log

| Step | Commit | Covered /62 | Notes |
|---|---|---|---|
| 01 baseline | 4472e87 | 26 | contract pinned, audit+tests added, no API changes |
| 02 shared cross-cutting | 6ae4e5a | 26 | errors/correlation/precondition normalized: details always object, retryable emitted for 429/503/504, 401/403/416 codes mapped, unhandled-500 keeps correlation IDs+headers, two-phase If-Match (early require_if_match + atomic in-txn check), nested write_txn via SAVEPOINT, backup import now atomic + bumps revision, Idempotency-Key bounds per contract (1..128) |
| 03 security boundary | e950498 | 26 | opaque BearerAuth on /api/v1 when OPAL_LOOK_TOKEN set (401 missing/malformed/invalid + WWW-Authenticate, OpalError envelope, X-Opal headers preserved); non-loopback bind refused without token; CLI sends OPAL_LOOK_TOKEN; token never logged/exported/echoed; dev mode stays open |
| 04 engines/models/capabilities | (this commit) | 27 | v1.5 Engine{id,name,version,enabled,state,tasks,device_types,options_schema} + EnginePatch{enabled,options}; Model{id,engine_id,display_name,tasks,state,resource_label,created_at} + ModelCreate{id,engine_id,resource_ref,tasks,options} + ModelPatch{display_name,options}; models table gained created_at/tasks/options/resource_ref (auto-migrated); model.enabled no longer API-settable (unavailable = warning not error); GET /capabilities/ computed from registries/settings; internal callers moved to engine_runtime/model_runtime |
| 05 sources + zones | (this commit) | 27 | v1.5 Source{id,kind,name,enabled,state,redacted_locator,last_frame_at,zones}; SourceCreate{id,kind,name,locator,secret_ref,options,zones,enabled} + SourcePatch{name,locator,secret_ref,enabled,options,zones}; kind enum rtsp/http/camera/file/media/image (host_video->file auto-migrated); sources.zones column added; zones replace-whole atomically; unique zone ids + polygon>=3/line==2/normalized-point validation; locator redaction on GET (scheme://authority) and export (redacted_locator); secret_ref nullable patch clears ref |

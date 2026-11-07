# OPAL-LOOK upstream v1.5.0 — Sequential Single-Commit Implementation Prompts

**Project:** `https://github.com/PatMartin/opal-look`
**Authoritative contract:** `openapi/opal_look_v1.5.0.yaml` + `openapi/shared/opal_kernel.yaml`
(OPAL Suite Kernel v1.2.0; 575 external `$ref`s — both files are normative).
**Superseded:** `opal_look_v1.5.0.yaml` (root) — the local "Simplified" draft the
codebase was previously migrated to. Kept unchanged as historical reference,
like `opal_look_v1.4.0.yaml`. `opal_look_v1.5.0_draft.yaml` is a byte-identical
duplicate; delete it in Prompt 01.
**Branch:** `feature/opal-look-1.5`; implement each numbered prompt one at a
time, inspect the result, then proceed. **No push.**

## What this migration is

The upstream v1.5.0 contract is **not** the simplified draft. It keeps the
v1.4-era resource model — sessions, profiles, rules, zones, captures,
artifacts — and modernizes it by extracting suite-standard surfaces into
`shared/opal_kernel.yaml` `pathItems` (engines, profiles, settings,
configuration/backup, health). The simplified-draft implementation restored
62/62 ops; the upstream spec defines 58 paths / ~76 ops with different
resource boundaries.

### Resources to restore (removed by commit c770b66)

| Resource | Ops | Notes |
|---|---|---|
| `/api/v1/profiles/` + `/{id}` + `/activate` | 6 | kernel `OpalProfile` (suite-generic; vision fills relevant fields) |
| `/api/v1/zones/` + `/{id}` | 5 | standalone; `Zone.source_id` replaces embedded `Source.zones` |
| `/api/v1/rules/` + `/{id}` | 5 | standalone detection rules; `capture_on_match`, `clip_on_match` |
| `/api/v1/sessions/` + `/{id}` + `/stop` + `/observations/` + `/stream` + `/preview` | 7 | full lifecycle is back |
| `/api/v1/sources/{id}/captures/` + `/api/v1/captures/*` | 5 | replaces `POST /sources/{id}/capture` |
| `/api/v1/artifacts/` + `/{id}` + `/content` | 4 | job/recording outputs (`artifact_ids`) |

### Shared resources to reconcile (shape changes)

- `Source`: drop `zones`, add `capabilities`.
- `Pipeline`: `stages` is the canonical body (`PipelineStage.portable`, `.phase`);
  no `model_id`/`task` shortcut fields.
- `Monitor`: gains `profile_id`, `current_session_id`; loses inline
  `conditions`/`publish_events` — durable desired-state that owns a session;
  standalone `Rule`s do detection.
- `AnalyzeRequest`: adds `profile_id`; `SourceInput` adds `capture_id`,
  `frame_at_ms`.
- `Job`/`Recording`: output `artifact_ids`/`artifact_id`.
- `Media`: slims to `{id,kind,mime_type,size_bytes,created_at,expires_at,
  duration_ms}`; **no `/content` endpoint** (bytes reachable via
  captures/artifacts only).
- `Observation`: gains `session_id`.
- `Engine` → kernel `OpalEngine` (`engine_id`, `description`, `available`,
  `options`, `metadata`).
- Settings → kernel `OpalSettingsMap`/`SettingRead`/`SettingUpdate`.
- Health → kernel `OpalHealthReport`/`OpalHealthProbe` (components, checks,
  uptime, broker_running, database_ready, pending_restart).
- Configuration → kernel `OpalConfigExport`/`OpalImportResult`/
  `OpalValidationReport` (suite sections; Look fills vision-relevant ones).
- `CapabilityCatalog`/`Metrics`: richer field sets.
- Remove: `POST /sources/{id}/capture`,
  `GET /sources/{id}/observations/stream`,
  `GET /monitors/{id}/observations/stream`, `GET /media/{id}/content`.

### Reusable machinery that carries over

`Store`/`write_txn`/repositories, correlation + access-log middleware,
OpalError envelope (already emits `retryable`), Bearer auth, two-phase
If-Match + global config revision, idempotency admissions, `LiveFramePump`,
RTSP/PyAV capture, synthetic engine, media byte store, SSE infra, Typer CLI
skeleton, SPA skeleton, contract_audit tool (needs external-`$ref` support).

## Test and reporting discipline

Identical to the v1.4→v1.5-simplified migration. Every prompt is
self-contained; run targeted **and** full tests; 1 cohesive commit per prompt;
never combine steps, push, or auto-start the next step. The contract audit
(retargeted in Prompt 01) is the progressive count and the final strict gate.

**Required agent result template**

```text
STEP: XX — title
INVESTIGATION: actual gap, evidence, alternatives considered
IMPLEMENTED: files and REST operations; known behavior changes
TESTS:
  targeted: <passed> / <failed> / <skipped>
  full pytest: <passed> / <failed> / <skipped>
  contract audit: covered <n>/<total>; missing <m>
  manual/hardware: <verified or NOT RUN; why>
CONFORMANCE: <implemented>/<total> v1.5 ops; <missing> missing
COMMIT: <local sha; never push>
REMAINING ISSUES: <specific known gaps and risks>
CONFIDENCE THIS STEP IS DEFECT-FREE: <0-100% + specific evidence>
OVERALL V1.5 CONFIDENCE: <not assessed until final strict audit>
```

## Prompts

### 01 — Pin the upstream contract; retarget the audit; measure the baseline

Commit `openapi/` (contract + kernel) as the authoritative spec; delete the
byte-identical `opal_look_v1.5.0_draft.yaml`. Extend `contract_audit` to
resolve external `./shared/opal_kernel.yaml#/components/pathItems/*` and
`#/components/*` `$ref`s when counting operations/paths (inline `x-opal-cli`
on the path level still counts). Repoint the audit's default contract to
`openapi/opal_look_v1.5.0.yaml`. Record the new baseline: total ops, covered,
missing, extra (implemented-but-not-in-contract). Update the ledger's pinned
inputs (new SHA-256, kernel version) and start a new ledger section. No REST
changes.

### 02 — Engines + health to kernel shapes

`GET /api/v1/engines/` and `GET/PATCH /api/v1/engines/{engine_id}` return
kernel `OpalEngine` (`engine_id`, `name`, `description`, `enabled`,
`available`, `options`, `metadata`, `version`, `state`, `tasks`,
`device_types`, `options_schema`); `OpalEnginePatch` `{enabled, options}`.
Health: `GET /health/` → `OpalHealthReport` (status, version, ready,
components, checks, uptime_seconds, broker_running, database_ready,
pending_restart, active_profile_id, metrics); `/live`, `/ready` →
`OpalHealthProbe` (status, ready, details, version).

### 03 — Settings + configuration to kernel shapes

`GET/PATCH /api/v1/settings/` → `OpalSettingsMap`;
`GET/PUT/DELETE /api/v1/settings/{key}` → `SettingRead`/`SettingUpdate`
(`value`, `updated_at`, `default`, `is_default`, `pending_restart`).
`GET /configuration/export` → `OpalConfigExport` (format_version,
exported_at, per-resource sections — Look fills engines/profiles/settings/
models/sources/pipelines/zones; suite-only sections absent or empty per
contract). `POST /configuration/validate` → `OpalValidationReport`;
`POST /configuration/import` → `OpalImportResult`. Preserve atomic import +
config-revision bump; fix the float-hours poisoning bug found earlier
(seconds→hours values must satisfy strict-int `ServiceSettings`, and no
stored override may ever make `effective_settings()` unvalidatable — that's
the no-recovery path).

### 04 — Profiles CRUD + activate (kernel shapes)

`GET/POST /api/v1/profiles/`, `GET/PATCH/DELETE /api/v1/profiles/{id}`,
`POST /profiles/{id}/activate` per kernel pathItems. `OpalProfile` is
suite-generic (voice/STT fields exist) — implement the vision-relevant
subset honestly: persist the contract fields the service can honor, reject
or ignore-with-warning fields it cannot per contract rules. `is_active`
single-active invariant + `activate` semantics; mutations are
config-revisioned (If-Match).

### 05 — Sources reconcile

`Source`/`SourceCreate`/`SourcePatch` to the new shapes: remove embedded
`zones` (now a standalone resource), add `capabilities`. Keep
kind/locator/secret_ref/status/probe/frame/stream semantics. Migrate or
drop embedded zone data (dev-stage: document which).

### 06 — Zones CRUD

`zones` table/repo; `GET/POST /api/v1/zones/`,
`GET/PATCH/DELETE /api/v1/zones/{id}`; `Zone{id,source_id,name,kind,points,
enabled}`; polygon ≥3 points / line ==2 / normalized-point validation;
`source_id` must reference an existing source (404/422 per contract);
config-revisioned writes.

### 07 — Rules CRUD

`rules` table/repo; full CRUD; `Rule{id,name,source_id,zone_id,kind,
class_filters,threshold,minimum_duration_ms,cooldown_ms,enabled,
capture_on_match,clip_on_match}`; validate `zone_id`/`source_id` refs and
`kind` enum; `capture_on_match`/`clip_on_match` are stored now and wired
when sessions evaluate (Prompt 10) — say so in the report.

### 08 — Pipelines canonicalized on stages

`Pipeline{id,name,stages,description,created_at}`, `PipelineCreate/Patch`
stages-only; `PipelineStage{id,kind,model_id,task,inputs,options,enabled,
portable,phase}`. Simple `{model_id,task}` admission becomes a single
inference stage internally if the contract permits — verify against the
schema before keeping any shortcut. `validate` returns issues on DAG
cycles, missing refs, unknown kinds/phases.

### 09 — Sessions lifecycle

`sessions` table/repo; `POST /sessions/` (start),
`GET /sessions/`, `GET /sessions/{id}`, `POST /sessions/{id}/stop`.
`Session{id,state,source_id,pipeline_id,created_at,started_at,ended_at,
processed_frames,dropped_frames,last_observation_at,failure}`;
`SessionCreate{source_id,pipeline_id,profile_id,options,retention,
auto_start}`. Resurrect the v1.4-era worker/pump machinery; honor
`auto_start`, admission limits, reconnect, and counter semantics.

### 10 — Session stream, preview, observations

`GET /sessions/{id}/stream` (MJPEG), `GET /sessions/{id}/preview`,
`GET /sessions/{id}/observations/` (session-scoped feed). Wire rule
evaluation + `capture_on_match`/`clip_on_match` here where the contract
requires match side-effects.

### 11 — Captures

`POST /sources/{id}/captures/` (`CaptureCreate{retain,annotate,session_id,
observation_id}`) + `GET /captures/`, `GET /captures/{id}`,
`DELETE /captures/{id}`, `GET /captures/{id}/content`. Exact-frame capture
semantics from the snapshots work; replaces `POST /sources/{id}/capture`.

### 12 — Artifacts

`GET /artifacts/`, `GET /artifacts/{id}`, `DELETE /artifacts/{id}`,
`GET /artifacts/{id}/content`. Job/recording outputs surface as artifacts
(`artifact_ids`); deletion guards per contract.

### 13 — Monitors reconcile

`Monitor{...,profile_id,current_session_id,...}`; drop
`conditions`/`publish_events` from API shapes. A running monitor owns a
session (`current_session_id`) — implement the monitor→session lifecycle
the contract describes.

### 14 — Analyze, jobs, recordings, observations, media reconcile

`AnalyzeRequest` +`profile_id`, `SourceInput` +`capture_id`/`frame_at_ms`;
`Job.artifact_ids`; `Recording.artifact_id`; `Observation.session_id`;
`Media` slim shape; remove `GET /media/{id}/content`.

### 15 — Capabilities, metrics, events

`CapabilityCatalog` full field set (stream_transports, export_formats,
limits, filters, visualization_modes, supports_raw_stream,
supports_motion_gate); `Metrics` full field set; `EventPublication` shape.

### 16 — Remove obsolete routes

`POST /sources/{id}/capture`, `GET /sources/{id}/observations/stream`,
`GET /monitors/{id}/observations/stream`, `GET /media/{id}/content`, and any
other implemented-but-not-in-contract `/api/v1` op. Audit's "extra ops"
count must reach 0.

### 17 — CLI re-mirror

Regenerate/hand-wire `opal-look` from the new contract's `x-opal-cli`
metadata: restore sessions/zones/rules/profiles/captures/artifacts groups;
`download` verbs for captures/artifacts; remove `observe`, old `capture`,
monitors `stream`, media `download`. Keep the error-handling fixes from the
CLI audit (no raw tracebacks; also drop the dead verbs that have no REST op).

### 18 — SPA re-mirror

Same for `/app/`: restore session/zone/rule/profile/capture/artifact
sections calling REST only.

### 19 — Certification

`contract_audit --strict` = 0 missing / 0 extra; full `pytest` green;
Spectral 0 errors on the new spec; Schemathesis smoke pass; update ledger +
AGENTS.md; final report with overall confidence.

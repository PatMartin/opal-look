# OPAL-LOOK v1.5.0 — Sequential Single-Commit Implementation Prompts

**Project:** `https://github.com/PatMartin/opal-look`  
**Authoritative contract:** `PatMartin/opal-api/openapi/opal_look.yaml` (v1.5.0 draft supplied in this conversation; not yet committed to OPAL-API).  
**Pinned local copy:** `opal_look_v1.5.0.yaml` at repository root, byte-for-byte from the downloadable draft; SHA-256 `b1c21e4ae435108ea302bdd0fa2a365d1e3b4a42f3d723b1cad7b513efdc6c2f`.  
**Branch:** `feature/opal-look-1.5`; implement each numbered prompt one at a time, inspect the result, then proceed. **No push.**

This contract is intentionally **breaking** despite retaining `/api/v1`. Keep any v1.4 production deployment on a separate instance or port; don't run old/new shapes together behind one path prefix. Intermediate commits are *partially* conformant, not production-ready. The REST interface is authoritative; the CLI and SPA are clients derived from it, never parallel implementations. Reuse the existing PyAV adapter, SQLite repo, error/correlation/ETag mechanics, Typer infrastructure and static JS SPA where correct.

## Initial preparation

1. Download the v1.5.0 draft YAML and place it as `opal_look_v1.5.0.yaml` in the `opal-look` root **without editing it**.
2. Create/switch to `feature/opal-look-1.5` from a clean branch (do not work on `main`).
3. Make sure the baseline environment runs `python -m pytest -q`; record initial failures rather than suppressing them.
4. Run Prompt 01, review its report and local commit; repeat through Prompt 28.
5. If implementation exposes a real contradiction or defect in the draft contract, STOP and propose a separate OPAL-API contract amendment. Don't make unreviewed spec changes just to make code pass.

## Test and reporting discipline

Every prompt below is self-contained. It includes the same execution/reporting protocol so it can be pasted into a separate coding-agent conversation. Targeted and full tests must both be run; CI cannot require actual camera/GPU/broker hardware. Counts must distinguish passed, failed, skipped, and **not run**. Add a runnable v1.5 contract audit in Prompt 01: it produces a truthful progressive count after every commit and becomes a hard pass/fail gate in Prompt 28. Keep 1 cohesive commit per prompt; never combine steps, push, or perform the next step automatically.

**Required agent result template**

```text
STEP: XX — title
INVESTIGATION: actual gap, evidence, alternatives considered
IMPLEMENTED: files and REST operations; known behavior changes
TESTS:
  targeted: <passed> passed / <failed> failed / <skipped> skipped
  full pytest: <passed> passed / <failed> failed / <skipped> skipped
  contract audit: <passed> passed / <failed> failed / <skipped> skipped
  CLI tests: <counts or NOT RUN>
  SPA tests: <counts or NOT RUN>
  manual/hardware: <verified or NOT RUN; why>
CONFORMANCE: <implemented>/62 v1.5 operations; <missing>/62 missing
COMMIT: <local sha; never push>
REMAINING ISSUES: <specific known gaps and risks>
CONFIDENCE THIS STEP IS DEFECT-FREE: <0-100% subjective assessment + specific evidence>
OVERALL V1.5 CONFIDENCE: <not assessed until final strict audit>
```

A subjective confidence score is *not* a statistical proof; a green unit suite alone does not justify 100%. If any required tests fail, do not commit. Broken legacy tests must be updated to v1.5 expected behavior, not deleted to obscure failures.

## Individual prompts

### 01. Pin the contract and create a measurable baseline

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Prerequisite: the user has downloaded `opal_look_v1.5.0_draft.yaml` from ChatGPT; copy it UNCHANGED into repo root as `opal_look_v1.5.0.yaml` and create the `feature/opal-look-1.5` branch. Inspect README, API routers, `schemas.py`, persistence, tests, CLI, and SPA. Add an offline contract-audit script/test to inventory all 62 operations/42 paths from this pinned YAML, map existing FastAPI routes and supported methods, flag missing/extraneous routes, and optionally validate OpenAPI 3.1/JSON-Schema references. Support a nonblocking migration-progress report now and a `--strict` switch that will fail on omissions in Step 28. Record a baseline full test run and initial gaps; write a short migration ledger with working vs missing vs legacy-only features. Ensure reporting is honest: missing routes aren't silently treated as passing. Keep the 1.4 YAML as historical reference, do not rewrite either contract, and don't implement API functionality here.
```


### 02. Normalize shared errors, correlation, and configuration ETags

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Audit `errors.py`, `correlation.py`, `precondition.py`, `Store.write_txn`, and routers against the v1.5 `OpalError`/`ErrorBody`, `X-Opal-*` headers, strong ETag/If-Match semantics and required HTTP statuses. Fix just the reusable cross-cutting mechanisms: structured error responses, propagation through JSON/binary/stream responses, atomic configuration revision handling (428 missing, 412 stale, 422 malformed), and separation of X-Opal-Session-Id logical context from internal worker/session IDs. Make runtime activity not bump configuration revisions. Include negative HTTP tests and transaction concurrency tests. Avoid broad endpoint/schema migrations; keep callers compatible until their step.
```


### 03. Enforce the documented security boundary

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Inspect current authentication, localhost binding defaults, bearer policy, static SPA access and stream security. Implement only the contract's security boundary: opaque BearerAuth on `/api/v1` as defined by the YAML, secure non-loopback exposure, safe token handling, and consistent 401/403 responses. Do not put bearer tokens in camera URLs, HTTP query strings, files, exports or logs. Preserve local development through explicit test auth fixtures instead of bypasses. Add unauthorized/authorized tests for JSON, binary and streaming endpoints and sensitive-data redaction. If the draft has inconsistent localhost/health auth rules, document that ambiguity and stop for contract clarification rather than inventing an exception.
```


### 04. Align engines, models, and capability discovery

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Migrate `/engines/`, `/engines/{engine_id}`, `/models/`, and `/models/{model_id}` to v1.5 fields, required properties, statuses, ETags and responses. Implement `GET /capabilities/` using actual registered adapters/models/source capabilities rather than hard-coded or aspirational flags. Reuse the existing model/engine registries and synthetic test engine; preserve the rule that registration references already provisioned assets (no downloads). Validate model/engine compatibility, unsupported task/options as 422, and deletion of referenced models as 409. Test missing/unavailable engine, capability-driven optional feature omission, and exact response-schema match. Do not add unrelated adapters.
```


### 05. Migrate sources and embed zones

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Update source CRUD to v1.5 `id`, `kind`, `name`, `locator`, `secret_ref`, `options`, `enabled`, and source-owned `zones`; remove externally exposed legacy `source_id`/`type` payloads from v1.5 routes. Migrate existing source records safely where possible; preserve old DB backups. Validate unique source-local zone IDs, polygon >=3 points, line exactly 2, normalized coordinates, and references from active consumers. PATCH zones replaces the entire collection atomically under ETag, not a deep merge. GET/export must redact locators/credentials. Keep source storage and credential references implementation-neutral. Test CRUD, conflict/ETag behavior, malicious URLs and zone input corner cases. Do not implement streaming here.
```


### 06. Make source probe, status, and frame access real

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement the v1.5 `/sources/{id}/status`, `POST .../probe`, and `GET .../frame`. Reuse existing `capture.py`, `capture_rtsp.py` (PyAV), adapter registration and `LiveFramePump`; investigate actual behavior before changing it. Return an actual current JPEG frame (not a placeholder), capture metadata/status and read-only connectivity diagnostics. Probe must not change logical configuration, start persistent processing or leak credentials. Frame GET must not implicitly perform inference or retention. Use fake PyAV/FrameStream and an in-memory test image to test reachable, unreachable, timeout, end-of-stream, cleanup, image fidelity, and content-type/correlation headers. Resource limits and failures must be explicit.
```


### 07. Implement simple pipeline CRUD and defaults

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `/pipelines/` and `/pipelines/{pipeline_id}` for the easy shorthand (`model_id` plus `task`) with `options` and `retention` defaults replacing profiles. Store revisions and ensure atomic ETag updates; reject missing/unavailable model and incompatible task. Include reference tracking to disallow deletion of a pipeline used by active monitors or work. Make `Settings.default_pipeline_id` resolvable without global profile activation. Persist pipeline definitions and migrate any recoverable profile settings carefully, without claiming all profile data can automatically become pipelines. Test add/list/show/update/remove, conflicts, defaults, and restart persistence. Do not implement advanced DAG execution here.
```


### 08. Validate advanced processing DAGs without running them

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement the second `PipelineCreate` mode: ordered `stages` with explicit inputs, no forward/cyclic references, task/model requirements, optional filter-only pipeline and strict portable filter/processing stage parameter validation. Implement `POST /pipelines/validate` as side-effect-free preflight validation returning the v1.5 issue schema. Enforce exactly one shorthand OR advanced mode, including atomic PATCH mode switches and explicit-null semantics. Invalid topology/control/engine capability must return the contract-defined validation response or 422, never be silently ignored. Use table-driven schema and semantic tests. Do not implement new execution/runtime stages in this commit.
```


### 09. Execute advanced pipelines with real stage semantics

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Build the minimal executor for validated DAGs: reuse one decoded frame where practical; run ordered preprocessing, registered inference, filters, motion-gated inference, presentation transforms, tracking if advertised, and annotations, with explicit capability failures. Keep original-image coordinate normalization for observations, separate inference-input from presentation-only filters, and distinguish motion unknown/warmup/discontinuity from no motion; periodic sampling must prevent indefinite skipped inference. Filter-only pipelines should work without an ML model. Use deterministic fake engines and ordered synthetic frames; assert stage order, no duplicate decode, motion unknown, skipped inference, unsupported controls, and memory/frame queue bounds. Don't add arbitrary plugin scripting or new filter types beyond the spec.
```


### 10. Align synchronous JSON analysis with observations

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `POST /api/v1/analyze/` using v1.5 `SourceInput` (one source_id or media_id), pipeline selection/default, `InferenceOptions`, `RetentionOptions`, and `AnalyzeResponse`. Adapt/reuse `analysis.py`; generate typed `Observation`/`ObservationItem` records and correct immutable stage provenance, revision, IDs and normalized boxes. One-shot requests must not create a public session. Test raw source current-frame, uploaded still, invalid mixed input, missing pipeline/default, unsupported task, model options, successful synthetic detections, and no default retention. Do not add multipart upload here.
```


### 11. Implement direct multipart still-image analysis

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `POST /api/v1/analyze/image` per the multipart schema: file plus optional JSON `request` form part, correct media types, request size/pixel limits, and JSON observations by default or rendered JPEG if `Accept: image/jpeg` is specified and supported. Never require a prior `/media/` upload and never persist the input implicitly. Reuse Step 10 inference path and existing Pillow/image validation. Test valid JPEG/PNG, file and request-part errors, 413/422 policy per contract, disabled rendering, content negotiation, annotations, correlations, and no saved media side effects.
```


### 12. Expose immutable retained observations

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `GET /observations/` and `GET /observations/{id}` on top of produced v1.5 typed observations. Persist only when requested by pipeline/monitor/request retention and within TTL/quota; default is metadata transient with no durable history. Include stable stage/model/pipeline provenance, source/media times, normalized coordinates, cursor pagination and filtering, deterministic order, 404/expiration policy, and no accidental mutation. Map old result history if a verified lossless migration is possible; otherwise preserve it separately until cutover and document the limit. Tests: opt-in/off, correct pagination/filter, immutable reads, expiry/sweep, concurrency and bounded retention.
```


### 13. Implement raw ephemeral MJPEG viewing

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `GET /sources/{source_id}/stream` with NO pipeline as a low-cost viewer. Reuse the proven source decoder/frame pump; stream valid multipart/x-mixed-replace JPEG boundaries and parts, enforce max viewers, finite buffers and frame dropping under backpressure, and release all viewer-specific decoder/worker resources on disconnect/errors. Viewer must not create a public session, monitor, artifact, observation, recording or persisted capture. Test streaming chunks with fake frames, client cancellation/cleanup, two viewers, disconnect/reconnect, auth, quotas and exact MIME/correlation headers. Do not add inference yet.
```


### 14. Add analyzed and annotated MJPEG viewing

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Extend the SAME `/sources/{source_id}/stream` with `pipeline_id`, `annotations`, presentation filters, classes, confidence, dimensions, quality and FPS as described in v1.5. Use a connection-scoped pipeline execution with default annotation behavior from the contract; never change persisted observation data or monitor execution when only the overlay parameters change. Validate unavailable pipeline/engine/filter/options, preserve no-inference raw path when pipeline absent, and release transient work on disconnect. Tests: annotated versus raw frames, class/threshold display filters, invalid query controls, multiple clients with isolated overlays, FPS/backpressure, and no implicit retention.
```


### 15. Add transient source observation SSE

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `GET /sources/{source_id}/observations/stream` as connection-scoped analysis output with SSE framing and heartbeats, using a required/selected pipeline as the v1.5 schema specifies. Do NOT add public session endpoints, durable replay or a second inference worker per subscriber without justification; it is distinct from monitor SSE. Ensure disconnection cancels temporary processing and returns capacity/errors clearly. Test event JSON conforms to `Observation`, event stream MIME, heartbeat, cancel/resource release, shutdown, malformed query and lack of unintended persistence. Leave durable monitor replay to Step 20.
```


### 16. Unify media representation and storage

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Replace separate user-facing upload/capture/artifact resource semantics with v1.5 `/media/` and `/media/{id}` + `/content`. Preserve the existing upload implementation while expanding stored immutable `Media` to enum `kind`/`origin`, provenance IDs, MIME, TTL, SHA-256, and exact content delivery. Support image and bounded video uploads, cursor/filter list, correct 404/410 policy, ranged download only where contract explicitly supports it, and 409 delete conflict while active referenced work uses bytes. Create one internal media-creation service reusable by later captures, jobs, recording and monitor clips. Preserve or migrate old stored media/snapshots without data loss. Test MIME sniffing, path traversal, retention, content bytes and conflicts. Avoid UI changes.
```


### 17. Capture exact current frames into unified media

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `POST /sources/{source_id}/capture` returning a v1.5 `Media` object with `kind=snapshot`, `origin=capture`, default no annotation, optional validated pipeline and retained exact-frame JPEG. Reuse the existing frame cache/annotation code only when it guarantees that the captured image corresponds to the selected frame; never substitute a different recent frame. Observe TTL limits, source authorization, unsupported annotation errors, and no implicit event publishing. Test exact image pixels/frame identity, captured and annotated variants, content retrieval via `/media/{id}/content`, expiry, quota/ETag independence and cleanup. Do not build recording here.
```


### 18. Implement persistent monitor lifecycle

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `/monitors/` CRUD and durable desired state: source_id, pipeline_id, enabled, options, retention, restart_policy. Reuse existing internal session worker/runtimes privately if helpful, but expose only v1.5 `Monitor` state and endpoints; no public session lifecycle. On restart recover enabled monitors correctly; disabled monitors must not process; stopping/removal closes workers; changing configuration uses If-Match and is atomic. Preserve viewer/recording independence and bound max_monitors/reconnect retries. Fake source tests must cover start, stop, restart, crash/retry, disabled state, missing dependencies, idempotent teardown, persistence and no implicit output retention.
```


### 19. Evaluate inline monitor conditions and source-owned zones

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `Monitor.conditions` instead of separate rules: object appearance/disappearance, enters/exits zone, line crossing, count threshold, dwell time and motion_detected, precisely as supported by advertised engine/tracking capabilities. Look up source-local polygons/lines and validate zone type, classes, threshold/duration/cooldown, and duplicate condition IDs; condition array PATCH replaces atomically. Avoid false disappearance or no-motion detection when frames drop, state resets or sources reconnect. The monitor emits typed matched-condition events internally, not arbitrary shell/HTTP actions. Test event sequence/transition/cooldown, threshold, coordinates, unsupported tracking and no duplicate triggers. Clip/snapshot-on-match must use unified media when supported, otherwise explicit capability failure.
```


### 20. Add durable monitor SSE with bounded replay

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `GET /monitors/{monitor_id}/observations/stream`, subscribed to ONE already running monitor without starting new analysis. Provide SSE observation and condition_match events, stable monotonic event IDs, bounded replay using Last-Event-ID, heartbeat, and deterministic 409 when requested cursor is stale (no silent restart at live head). Backpressure must drop/limit subscribers rather than grow memory without bound, and disconnect must not stop monitor. Tests: two clients share one analysis producer, replay/no replay, stale cursor, event order, disconnect, bounded buffers, zero unauthorized leaking, and correct content type/correlation headers.
```


### 21. Publish monitor detections through OPAL-EVENT

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Connect monitor condition matches and the v1.5 event envelope to the existing `events.py` publisher, without duplicating OPAL-EVENT's rules/actions. Respect global events_enabled, allowlist, monitor publish_events opt-in, bounded queue, best-effort drops and loop protection; external transport is configured out of band. Publish failure must never break inference or the HTTP request. Reuse the OPAL suite's two-frame ZeroMQ topic/message convention and `data.metadata` correlation fields. Validate source/monitor IDs and no credential/camera-frame leakage in default event payload. Fake transport tests: enabled/disabled, filtered topic, queue exhaustion, broker failure, correlation propagation, nonblocking behavior. `/events/status` itself is completed in Step 25.
```


### 22. Implement finite jobs and cancellation

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `/jobs/` POST/GET and `/jobs/{job_id}` GET, `/cancel` for bounded finite `video_analysis` and `media_export`. Use validated source/media selection and explicit pipeline settings, accept Idempotency-Key (exact replay returns original job; mismatched replay 409; 24h reservation), create progress/state transitions, support cooperative cancel and restart handling, bounded concurrency, and output unified `media_ids`. Results and derived media must retain provenance; do not allow arbitrary path access, implicit permanent storage or unbounded full-video buffering. Use small generated synthetic video fixtures for job completion/cancel/error/retry tests; verify output retrieval and no partial-file leaks.
```


### 23. Implement explicit independent recordings

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement `/recordings/` start/list, `/recordings/{id}` show and `/stop` using the same capture runtime and unified media store. Start recording ONLY on explicit request; honor audio, duration cap, optional annotated pipeline, and output capabilities. Use idempotent admissions, states starting/recording/stopping/completed/failed, stop-to-finalize with eventual `media_id`, safe cleanup of interrupted/failed recording, and bounded disk use. Viewing/disconnecting never starts/stops a recording. Test deterministic fake stream, lifecycle, repeated stop/idempotency, output MIME and bytes, audio/annotation unsupported 422, source removal conflicts and disk quota.
```


### 24. Align settings and safe portable configuration

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Migrate existing one-setting-at-a-time REST (`GET/PUT/DELETE /settings/{key}`), whole-map GET/PATCH, and old `/backup` endpoints to canonical v1.5 `/configuration/export`, `/configuration/validate`, `/configuration/import` with typed `Settings` fields and default_pipeline_id. Keep atomic strong ETag behavior and distinguish logical config from runtime state. Export must redact locators/secrets and omit media/history; import uses `ConfigurationImport.source_bindings` to explicitly resolve redacted locators, validates all source/model/pipeline/monitor references and applies replacement atomically. Validate is nonmutating and gives concrete issues. Add test for export/rebind/import and rollback on bad input, concurrent ETag, legacy backup preservation or documented non-contract migration. No silent data loss.
```


### 25. Close operational/diagnostic and quota gaps

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Implement/align v1.5 `GET /health/`, `/health/live`, `/health/ready`, `/metrics/`, `/events/status`. Verify auth/correlation/errors on ALL response kinds and quotas for max_viewers, max_monitors, max_jobs, uploaded bytes, source FPS, frame cache, SSE replay and retention. Confirm no unbounded queues, leaked tasks, source credentials, or non-loopback insecure bind. Use repeatable stress/failure tests (fake frames and broker) for disconnect storms, reconnection, saturation, retention sweep, missing engines and graceful shutdown. This commit is operational hardening ONLY—don't add new features or rewrite unrelated code. Update the conformance ledger with any remaining gaps.
```


### 26. Make Typer CLI faithfully mirror v1.5 REST

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Audit `src/opal_look_cli/cli.py`, `client.py` and old generated collection helpers. Regenerate or hand-wire CLI ONLY from the now-implemented REST operations and v1.5 `x-opal-cli` group/command metadata: resource verbs add/remove/update/list/show; special view, frame, observe, capture, validate, run, cancel, start, stop, stream, download, etc. Use kebab-case flags, support URL/auth/correlation/ETag, show clear errors and JSON output. Remove CLI commands with no REST operation (current generator emits some) and remove obsolete profile/session/result/snapshot client flows. `view`/`stream` must handle streaming rather than buffering indefinitely, with practical local display/URL behavior that honestly reflects bearer auth limitations. CLI must not query SQLite, decode video or implement separate inference. Mock HTTP tests must assert method/path/body/header against all intended CLI commands and correct exit codes.
```


### 27. Make the SPA faithfully mirror v1.5 REST

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Update `src/opal_look/static/app.js`, HTML/CSS to use ONLY the v1.5 REST contract, not legacy profiles, sessions, results, snapshots, or backups. Screens should cover sources/zones, pipelines simple+advanced configuration or JSON editor, one-frame analyze, raw/annotated live camera view, monitors/conditions and stream results, observations, media, jobs, recordings, settings and configuration, capabilities/health. Do NOT invent separate UI backend endpoints. Implement bearer-authenticated MJPEG/SSE via secure fetch/approved same-origin auth infrastructure; never put tokens in query strings or local persisted URLs, and cancel streams when navigating away. Align optimistic concurrency with ETag, display clear unsupported capability messages, and ensure each action corresponds to an actual REST operation. Use automated browser/smoke or JS tests where tooling exists; record manual-only portions separately. Test key user flows and failure displays.
```


### 28. Remove obsolete routes and certify full conformance

```text
You are implementing OPAL-LOOK in https://github.com/PatMartin/opal-look, on the existing local `feature/opal-look-1.5` migration branch. The authoritative target is the exact pinned `opal_look_v1.5.0.yaml` copied from the OPAL-API v1.5.0 draft. Read the relevant YAML paths, request/response schemas, error responses, security requirements, and x-opal-cli metadata BEFORE editing. Investigate the existing code/tests first; reuse working components and do not create an alternate contract, unrequested abstractions, or an independent CLI/SPA behavior model. Scope this commit only to the task below. Write deterministic tests using fakes; no internet, real camera, GPU, or external broker should be required for normal CI. Keep all existing contract-compatible behavior, adjust obsolete tests when replacing an incompatible public contract, and do not mark failures as skipped/xfail to make CI green. Preserve OPAL errors/correlation, strong configuration ETags, explicit capability checks, bounded resources, privacy and secret redaction as applicable. Run targeted tests, full `pytest -q`, and the evolving contract audit before commit; if anything fails, fix it or STOP WITHOUT COMMITTING. Never push. When successful, make exactly ONE local cohesive commit, then STOP for review.

Report: (1) what you found and changed; (2) REST paths/schemas covered; (3) commands run and the exact passed/failed/skipped counts for targeted tests, full suite, contract checks and any CLI/SPA checks (mark any not run, never invent counts); (4) a local commit SHA; (5) remaining known gaps, risks and hardware-only tests; (6) your evidence-based confidence, 0–100%, that THIS COMMIT has no remaining known defects, with explanation. Separately state cumulative v1.5.0 operation coverage as implemented/62 and still missing/62. Never claim whole-contract conformance before the final strict audit.

TASK SPECIFIC TO THIS COMMIT:
Final strict cutover only after 01–27 are committed and green. Remove public v1.4-only `/profiles`, `/sessions`, `/results`, `/snapshots`, `/backup`, `/devices/cameras`, and incompatible route aliases unless the v1.5 YAML explicitly defines them. Retain private worker code if useful and user data safely; don't delete legacy tables or data until proven migrated/unused. Switch audit to `--strict`: assert exact 42 paths, 62 method/paths, operation metadata, no accidental extra `/api/v1` operations, request+response schema tests, statuses/headers including binaries and SSE, CLI mapping, SPA endpoint inventory, and security. Run full pytest, offline schema/contract tooling, clean SQLite migration, multi-client streams, monitor/restart/conditions/SSE, jobs, recordings, import/export, events, CLI and browser smoke. Generate a dated conformance scorecard mapping every operation to tests; explicitly list unsupported optional capability-gated functionality and any unverified hardware behavior. Make ONE final local commit only with 0 failing required tests and 0 missing operations. Do not push or declare 'no possible problems'.
```


## Operation coverage by implementation step (all 62 operations mapped)

| Acceptance step | Operations |
|---:|---:|
| 01 — Pin the contract and create a measurable baseline | 0 |
| 02 — Normalize shared errors, correlation, and configuration ETags | 0 |
| 03 — Enforce the documented security boundary | 0 |
| 04 — Align engines, models, and capability discovery | 9 |
| 05 — Migrate sources and embed zones | 5 |
| 06 — Make source probe, status, and frame access real | 3 |
| 07 — Implement simple pipeline CRUD and defaults | 5 |
| 08 — Validate advanced processing DAGs without running them | 1 |
| 09 — Execute advanced pipelines with real stage semantics | 0 |
| 10 — Align synchronous JSON analysis with observations | 1 |
| 11 — Implement direct multipart still-image analysis | 1 |
| 12 — Expose immutable retained observations | 2 |
| 13 — Implement raw ephemeral MJPEG viewing | 0 |
| 14 — Add analyzed and annotated MJPEG viewing | 1 |
| 15 — Add transient source observation SSE | 1 |
| 16 — Unify media representation and storage | 5 |
| 17 — Capture exact current frames into unified media | 1 |
| 18 — Implement persistent monitor lifecycle | 5 |
| 19 — Evaluate inline monitor conditions and source-owned zones | 0 |
| 20 — Add durable monitor SSE with bounded replay | 1 |
| 21 — Publish monitor detections through OPAL-EVENT | 0 |
| 22 — Implement finite jobs and cancellation | 4 |
| 23 — Implement explicit independent recordings | 4 |
| 24 — Align settings and safe portable configuration | 8 |
| 25 — Close operational/diagnostic and quota gaps | 5 |
| 26 — Make Typer CLI faithfully mirror v1.5 REST | 0 |
| 27 — Make the SPA faithfully mirror v1.5 REST | 0 |
| 28 — Remove obsolete routes and certify full conformance | 0 |

The CSV enumerates all method/path/operationId combinations. This is a **planning coverage check**, not evidence the operations are implemented.

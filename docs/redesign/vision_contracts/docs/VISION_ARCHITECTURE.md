# OPAL Composite Vision Architecture

**Status:** Design baseline / contract draft, not deployed  
**Scope:** Unified `opal look` and independent YOLO, RF-DETR, RT-DETR, D-FINE adapters  
**Suite dependency:** [`openapi/shared/opal_kernel.yaml`](https://github.com/PatMartin/opal-api/blob/main/openapi/shared/opal_kernel.yaml)  
**Current inspected OPAL reference:** `opal-api` main, `opal_kernel.yaml` **1.7.1** (SHA `0773c5fea4ac2dd4e96536e630ec9a26a5232ec5`), `opal_look.yaml` **1.7.1**  
**Contract version of this proposal:** `0.1.0-draft`

## Executive decision

**Do not merge `vision_kernel.yaml` into `opal_kernel.yaml`.** The existing OPAL kernel remains authoritative for suite-wide conventions. The vision kernel composes its reusable schema, parameter and Path Item definitions through external `$ref`, then the four independent engine contracts reference both kernels. For publishing, bundle the dependency graph into each standalone API artifact. The only likely OPAL-kernel change is a later *optional* clarification of existing `OpalEngine`/`EngineId` descriptions that currently mention TTS; that is not required to design the vision interfaces.

```text
opal-api/openapi/
├── shared/
│   ├── opal_kernel.yaml            Existing suite-wide source of truth; unchanged
│   └── vision_kernel.yaml          New, vision-specific shared components
├── engines/
│   ├── yolo.yaml                   Independent REST adapter
│   ├── rfdetr.yaml                 Independent REST adapter
│   ├── rtdetr.yaml                 Independent REST adapter
│   └── dfine.yaml                  Independent REST adapter
└── opal_look.yaml                  Existing application contract; integrate carefully
```

Runtime independence is a deployment property: an engine adapter may use schema definitions from OPAL without requiring `opal-look`, `opal-devices`, `opal-flow`, or other OPAL service processes.

## Contracts and boundaries

| Component | Owns | Does not own |
|---|---|---|
| `opal_kernel.yaml` | Four correlation headers, OpalError, strong ETags/If-Match, security conventions, suite settings, reusable health/info/engines routes and `x-opal-cli` rules | Detection data types |
| `vision_kernel.yaml` | Common model, inference, geometry, frame, training, export, benchmarking, job, artifact, provenance schemas and reusable Path Items | A running REST service or a physical model registry |
| YOLO / RF-DETR / RT-DETR / D-FINE REST adapters | Their own model weights, model lifecycle, inference, training, export, engine-native capabilities, bounded execution queues | Global camera inventory, common vision DAGs |
| `opal-look` | Composite engine discovery, selection/fallback, sources, live sessions, vision DAGs, tracking, analytics, fusion, normalized output and federated model **metadata** | Ownership of weights, mandatory engine dependencies, centralized GPU scheduling |
| `opal-devices` (optional) | Audio/video/compute device discovery, metadata, availability, peer federation | Opening cameras, media streaming, hardware allocation, model eviction |
| `opal-flow` | Workflows involving multiple OPAL services | Implementation of frame-level vision DAGs |
| `opal-event` (optional) | Event distribution, rules and actions | Inference and device ownership |

**Important current-state finding:** The inspected `opal_look.yaml` v1.7.1 already defines sources, pipelines, sessions, jobs, artifacts, `/api/v1/analyze/`, `/api/v1/analyze/image`, engine discovery and normalized observations. Do **not** introduce parallel duplicate `opal-look` endpoints mechanically. This package defines reusable domain and independent adapter contracts; the eventual `opal_look.yaml` migration needs a **separate, explicit operation-level diff**. In particular, current Look says model download, training and provider provisioning are **out of scope**; that should be preserved as an intentional application boundary unless explicitly revised. A unified CLI may delegate selected commands to engine adapters without making `opal-look` itself the model owner.

## The 35 ratified decisions

| # | Area | Final decision | Implication |
|---:|---|---|---|
| 1 | Shared kernel | Comprehensive | Shared detection, models, training, validation, export, benchmarks and jobs |
| 2 | Extensions | Typed options **and** distinct operations | Extend parameters for variations; add endpoints for new behavior |
| 3 | Prediction results | Normalized + optional native | Consumers get stable output without losing engine data |
| 4 | CLIs | Unified + independent | `opal look`, `yolo-cli`, `rfdetr-cli`, `rtdetr-cli`, `dfine-cli` |
| 5 | Capability discovery | Engine + model + runtime | Never infer per-model support from engine branding |
| 6 | Prediction tasks | `predict --task` + CLI aliases | `detect`, `segment`, `pose` etc. are aliases, not duplicate REST calls |
| 7 | Integration | Python plugins + REST adapters | Implementations can be in-process or independently deployed |
| 8 | Instance selection | Explicit, automatic, preferences | `--instance gpu-server` or `--instance auto` |
| 9 | Fallback | Configurable | `none`, `instance`, `engine`; explicit instance defaults to none |
| 10 | Inputs | Hybrid | Direct references, uploads and network streams with source-aware transport |
| 11 | Live inference | REST + SSE + optional WebSocket | Look manages session, engine processes frames |
| 12 | Tracking | Common + optional native | Uniform tracks; do not remove YOLO-native tracking |
| 13 | Analytics | Common + native extensions | Reuse normalized detections for zones, counts, speed, heatmaps |
| 14 | Pipelines | Composable vision workflows | Camera → detector → tracker → analytics; not a general workflow engine |
| 15 | Pipeline topology | Linear-first + optional DAG | Branches/merges only when needed; cycles prohibited |
| 16 | Pipeline failure | Per-step error policy | `stop`, bounded `retry`, safe `skip` |
| 17 | Pipeline data | Typed, extensible | Validate stage input/output compatibility ahead of execution |
| 18 | Buffering | Configurable bounded queues | `drop-oldest`, `drop-newest`, `block`; expose drops/latency |
| 19 | Frame identity | Common envelope | Frame, source, run, sequence, time and correlation fields |
| 20 | Branch joins | Configurable `all/any/quorum` | Timeout and provenance for missing branches; default all |
| 21 | Multi-engine fusion | Optional algorithms | none, NMS, weighted boxes, consensus; preserve originals |
| 22 | Classes | Extensible canonical taxonomy | Per-model native-to-canonical mappings; unmapped labels retained |
| 23 | Geometry | Normalized pixels + optional native | xyxy, OBB, polygon, mask, keypoints, original-frame transforms |
| 24 | Large output | Inline + referenced artifacts | Size caps, content type, explicit output mode and retention |
| 25 | Reproducibility | Execution manifests | Weights/input hashes, runtime, options, instance, actual fallback |
| 26 | Benchmark | Common + native metrics | p50/p95/p99, FPS, mAP where applicable, memory and methodology |
| 27 | Model location | Federated metadata, engine-owned weights | One logical inventory, no centralized model file storage |
| 28 | Model installation | Explicit only | No silent downloads or replication |
| 29 | Model discovery cache | Cached + periodic + on-demand | Stale model is not claimed runnable |
| 30 | Model identity | Logical ID + installation ID | Same file name does not establish same weights |
| 31 | Model updates | Explicit, versioned | Preserve older weights; pin versions/checksums |
| 32 | Model removal | Explicit with dependency checks | Dry-run; reject deletion of active models; per-installation |
| 33 | Residency | Engine-managed policies | On-demand / keep-loaded / idle-timeout |
| 34 | Concurrency | Engine-managed bounded queues | Per-engine limits and workload reports |
| 35 | Overload | Reject / bounded wait / permitted fallback | No indefinite waits or unsafe duplicate stateful jobs |

## Execution and discovery

```text
                        opal look --engine=... --instance=...
                                       |
                          discover engines/plugins
                                       |
                     engine + model + runtime capability check
                                       |
                           select instance / apply policy
                                       |
             +-------------------------+-------------------------+
             |                                                   |
     in-process Python adapter                            REST adapter
             |                                                   |
       installed engine                                    remote engine
             |                                                   |
       engine-owned models                                 engine-owned models
             +-------------------------+-------------------------+
                                       |
                         normalized response / artifacts
                                       |
                              tracking / analytics /
                             DAG joins / optional fusion
```

**Selection semantics:** `--engine` selects a family, `--instance` selects a deployment, `--runtime` selects an execution backend, `--model` selects weights, and `--device` identifies execution hardware. Plugins provide integration; they are not synonymous with engines. Default instance selection may respect local preferences. If the operator explicitly picks an instance, no fallback is implied. Cross-engine switching requires explicit permission. Stateful operations with uncertain outcomes must not be silently replayed.

## Typed inference and extension contract

One common `POST /api/v1/predict` accepts a task selector, source, model identity, runtime and shared options. The four engine YAMLs specialize `engine_options` with individual JSON Schemas; unsupported options MUST return 422 instead of being silently ignored. Engine-specific operations, such as Ultralytics track/tune/solutions, use additional paths because the workflow is meaningfully different.

Standard geometry references the original orientation-corrected image in pixels. The shared `FrameEnvelope` remains attached to results across branches and stage boundaries. Tracking identifiers are ephemeral within the tracking session. Class taxonomy maps native labels explicitly; a parent category such as `vehicle` must not be collapsed to `car` without an explicit rule. Fusion never discards the contributing raw detections.

**Extension rule (OPAL design tenet):** *If a capability performs an existing operation differently, extend its parameters. If it performs something meaningfully different, extend the API.*

## Suite kernel compatibility

| OPAL kernel v1.7.1 primitive | Vision reuse |
|---|---|
| `OpalSessionIdParameter`, `OpalTransactionIdParameter`, `OpalRequestIdParameter`, `OpalCausationIdParameter` | All routed operations and native engine operations |
| `OpalSessionIdHeader`, `OpalTransactionIdHeader`, `OpalRequestIdHeader`, `OpalCausationIdHeader` | Successful/failed HTTP responses, including binary results |
| `OpalError` and reusable error responses | Standard 4xx/5xx JSON bodies |
| `IfMatch`, `ETag` | Mutable model configurations and destructive model removal where applicable |
| `IdempotencyKey` | Asynchronous admissions for train/install/export where safe |
| `BearerAuth`, `x-opal-authorization` | Non-loopback protection and privileged mutations |
| `health`, `health_live`, `health_ready`, `info`, `info_ping` Path Items | Mounted without redefinition |
| `engines_collection`, `engine_item` Path Items | Mounted with existing `OpalEngine` semantics |
| `settings_collection`, `settings_key` Path Items | Engine-local settings and concurrency policy |
| `x-opal-cli` | Maps REST operations to Typer commands |

**Caveat:** The OPAL kernel currently contains legacy `OpalEngine` and `EngineId` descriptive strings referring to TTS/Say. This draft reuses the same structural contract but does not modify its descriptions. A separate documentation-only kernel revision would make this terminology more domain-neutral later. No merge is required.

## Independent contracts vs the unified CLI

The four adapter specs are **standalone REST APIs**. They cover each engine's own models, predict/train/validate/export/benchmark and jobs. They deliberately do not each implement Look's zones, pipeline DAGs, RTSP session ownership, arbitrary camera registration or central GPU scheduler.

The `VISION_CLI.md` includes the desired unified Typer CLI. Commands assigned to Look's application layer—such as `pipelines`, `streams`, `trackers`, `analytics`, `fusion`, `classes`, `plugins` and `engines instances`—are **not** implied to exist in the independent engine adapter specs. They must be reconciled into the existing `opal_look.yaml` contract, avoiding duplicate routes. A capability alias like `segment` dispatches to the same prediction operation, not a new REST route.

## Open design issues to validate during implementation

1. **Kernel path version pinning.** The proposal targets current 1.7.1 source. Pin a commit/tag in release CI and re-bundle on kernel upgrades.
2. **Schema strictness.** Engine `engine_options` objects are typed and closed, but generic request envelopes intentionally permit extension fields for composite operation reuse. Tighten at the final assembled schema boundary when tooling supports exact unevaluated-property handling.
3. **OpenAPI CLI generator.** `x-opal-cli` is informative in the YAML; test generated command trees against it and enforce no command collisions.
4. **OPAL Look reconciliation.** Existing Look has routes and contract decisions that must not be silently replaced. In particular, adapt `models discover`, unified `train`, `export` and benchmark delegation carefully to the existing architecture.
5. **Security of remote media.** Protect against SSRF, unintended private-address access, path traversal, untrusted external URLs, leaked camera credentials and unauthenticated artifact downloads.
6. **Streaming protocols.** REST/SSE paths belong at Look's application layer; WebSocket negotiation requires an explicit deployment contract and capability gating.
7. **Benchmark comparability.** Same datasets, preprocessing, precision, device and measurement scope are prerequisites for meaningful comparisons. Do not equate confidence scales between models.
8. **Validation status.** YAML, local references, known suite-kernel symbols and extension schemas are tested locally. Full bundling against the *actual* OPAL kernel requires making that file available under `openapi/shared/opal_kernel.yaml`.

## Incremental rollout

1. Place `vision_kernel.yaml` alongside the existing OPAL suite kernel; do **not** change it.
2. Validate and bundle the four engine specs independently; require each to run without `opal-look`.
3. Implement common results, capability discovery, model and runtime introspection first.
4. Add predict and typed engine options; test result geometry and error conventions.
5. Add asynchronous lifecycle with model ownership, manifests, explicit installs and removal checks.
6. Produce an operation-by-operation migration plan against existing Look 1.7.1 before adding unified CLI integrations.
7. Implement a minimal unified CLI with engine/instance discovery and inference; follow with optional tracking, DAG, analytics, fusion and artifact orchestration.

This is a **proposal**. It has not been committed to GitHub, run against live engine implementations, or approved as a replacement for the existing Look contract.

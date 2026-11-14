# Composite Vision — Python Typer CLI Reference

**Status:** Proposed interface, not implemented  
**Unified executable:** `opal look`  
**Independent executables:** `yolo-cli`, `rfdetr-cli`, `rtdetr-cli`, `dfine-cli`  
**Contract sources:** `vision_kernel.yaml` and four engine OpenAPI 3.1 contracts  
**Suite conventions:** `opal_kernel.yaml` 1.7.1, `x-opal-cli`, four correlation headers, OpalError

This reference implements the 35 agreed design decisions at the **CLI-design level**. It differentiates commands that have an independent engine REST operation in this package from commands that will require **a separate integration diff against the existing `opal_look.yaml` v1.7.1**. Do not assume all commands below are already available in a deployed `opal-look`.

## 1. Unified CLI tree

```text
opal look
├── health
├── version
├── capabilities
│
├── engines
│   ├── discover
│   ├── list
│   ├── show
│   ├── capabilities
│   ├── instances
│   └── defaults
│       ├── list
│       ├── set
│       └── remove
├── plugins
│   ├── discover
│   ├── list
│   ├── show
│   ├── enable
│   └── disable
├── runtimes
│   ├── discover
│   ├── list
│   ├── show
│   └── capabilities
├── models
│   ├── discover
│   ├── list
│   ├── show
│   ├── capabilities
│   ├── instances
│   ├── versions
│   ├── install
│   ├── load
│   ├── unload
│   ├── remove
│   └── settings
│       ├── list
│       └── update
│
├── predict
├── detect       (alias: predict --task detect)
├── segment      (alias: predict --task segment)
├── classify     (alias: predict --task classify)
├── pose         (alias: predict --task pose)
├── obb          (alias: predict --task obb)
├── depth        (alias: predict --task depth, capability-gated)
├── embed        (alias: predict --task embed, capability-gated)
├── track        (native tracker or common Look tracker)
│
├── trackers
│   ├── list
│   ├── show
│   └── capabilities
├── analytics
│   ├── count
│   ├── line-crossing
│   ├── zones
│   ├── heatmap
│   ├── speed
│   └── distance
├── solutions
│   ├── list
│   ├── show
│   └── run
├── classes
│   ├── list
│   ├── show
│   ├── add
│   ├── update
│   ├── remove
│   └── mappings
│       ├── list
│       ├── set
│       └── remove
│
├── streams
│   ├── list
│   ├── create
│   ├── show
│   ├── start
│   ├── stop
│   ├── watch
│   └── remove
├── pipelines
│   ├── list
│   ├── add
│   ├── show
│   ├── update
│   ├── remove
│   ├── validate
│   ├── start
│   ├── stop
│   ├── status
│   ├── watch
│   ├── metrics
│   └── steps
│       ├── list
│       ├── add
│       ├── show
│       ├── update
│       ├── remove
│       └── connect
│
├── train
├── validate
├── export
├── benchmark
├── benchmarks
│   ├── run
│   ├── list
│   ├── show
│   ├── compare
│   └── export
├── jobs
│   ├── list
│   ├── create
│   ├── show
│   ├── cancel
│   └── logs
├── executions
│   ├── list
│   ├── show
│   ├── manifest
│   └── reproduce
├── artifacts
│   ├── list
│   ├── show
│   └── download
├── settings
│   ├── list
│   ├── show
│   ├── update
│   └── remove
└── status
```

**Tree conventions:** common root engine selectors may precede the command (`opal look --engine yolo --instance gpu-server predict ...`). As an ergonomic convenience, the same selectors may be accepted after the command, but CLI generation must pick one canonical binding and test both carefully if both are supported. `engines`, `plugins` and `runtimes` are **different concepts**: inference selection, integration installation, and execution environment, respectively.

### Core options on unified operations

| Option | Purpose | Example |
|---|---|---|
| `--engine` | Engine family or `auto` | `yolo`, `rfdetr`, `rtdetr`, `dfine`, `auto` |
| `--instance` | Installed local/remote engine instance or `auto` | `gpu-server` |
| `--runtime` | Execution backend | `pytorch`, `tensorrt` if supported |
| `--device` | Compute hardware | `cuda:0`, `cpu` |
| `--model` | Model identity/weights | `yolo26n.pt` |
| `--fallback` | Allowed rerouting | `none`, `instance`, `engine` |
| `--on-overload` | Overload handling | `reject`, `wait`, `fallback` |
| `--timeout-ms` | Bounded wait/operation deadline | `5000` |
| `--output-mode` | Result materialization | `auto`, `inline`, `reference` |
| `--include-native` | Include engine-native diagnostic result | flag |
| `--task` | Prediction result task | `detect`, `segment`, `classify`, `pose`, `obb` |
| `--source` | Image path, video file, HTTP URI or RTSP URI | `image.jpg`, `rtsp://...` |
| `--upload` | Force multipart media upload | `image.jpg` |
| `--refresh` | Recheck remote metadata | flag |
| `--include-stale` | Show stale inventory entries | flag |

A missing capability must be rejected with a stable error, not silently replaced by a different operation. `--engine auto` chooses an appropriate installed engine; it is not a mandatory dependency on any particular framework. Automatic selection should disclose the selected engine/instance/model/runtime in its result and reproducibility manifest.

## 2. Four independent Typer CLIs

Each standalone client talks to its own independently running REST adapter. The shared command set is generated from `vision_kernel.yaml` and the engine contract. It must work with **no opal-look, opal-flow or opal-devices process running**.

```text
Independent common commands (all four):
<executable>
├── health
├── version
├── capabilities
├── engines
│   ├── list
│   └── show
├── models
│   ├── list
│   ├── show
│   ├── capabilities
│   ├── versions
│   ├── instances
│   ├── install
│   ├── load
│   ├── unload
│   └── remove
├── runtimes
│   ├── list
│   └── show
├── predict
├── train
├── validate
├── export
├── benchmark
├── jobs
│   ├── list
│   ├── create
│   ├── show
│   ├── cancel
│   └── logs
├── artifacts
│   ├── show
│   └── download
├── executions
│   ├── list
│   ├── show
│   ├── manifest
│   └── reproduce
└── settings
    ├── list
    ├── show
    ├── update
    └── remove
```

Dedicated capabilities:

```text
yolo-cli                     rfdetr-cli           rtdetr-cli          dfine-cli
├── (common)                 ├── (common)         ├── (common)        └── (common)
├── detect (alias)           ├── detect (alias)   └── detect (alias)
├── segment (alias)          ├── segment (alias)
├── classify (alias)         └── pose (preview; if supported)
├── pose (alias)
├── obb (alias)
├── track (native workflow)
├── tune (native workflow)
└── solutions
    └── run
```

Task aliases do **not** introduce new REST endpoints. Only expose an alias when the installed model and runtime advertise support. RF-DETR pose/keypoints are backend/model-conditional. The RT-DETR and D-FINE adapters expose additional typed options on common commands, not invented operations named `decoder`, `refinement` or `predict-advanced`.

### Independent CLI examples

```bash
# All four use one common detector result schema

yolo-cli predict --model yolo26n.pt --task detect --source image.jpg
rfdetr-cli predict --model nano --task detect --source image.jpg
rtdetr-cli predict --model rtdetrv2-s --task detect --source image.jpg
dfine-cli predict --model dfine-s --task detect --source image.jpg

# Task alias = a predictable specialization of the same REST operation
yolo-cli segment --model yolo-seg.pt --source image.jpg

# Engine-native YOLO extension, not a duplicate common operation
yolo-cli track --model yolo26n.pt --source video.mp4 --tracker bytetrack

# Typed engine options; support MUST be capability-advertised first
rtdetr-cli predict --model rtdetrv2-s --source image.jpg --decoder-layers 4
```

## 3. Standalone CLI → REST mappings

For all four engine adapters, the generated CLI uses the same relative paths. The base address is configured per standalone service (for example `http://127.0.0.1:8000`). HTTP methods are from the YAML files; these are real *proposed contract mappings*.

| CLI command | HTTP | REST path | Reusable source |
|---|---|---|---|
| `capabilities` | GET | `/api/v1/capabilities/` | Vision |
| `engines list` | GET | `/api/v1/engine/` | OPAL |
| `engines show` | GET | `/api/v1/engine/{engine_id}` | OPAL |
| `models list` | GET | `/api/v1/model/` | Vision |
| `models show` | GET | `/api/v1/model/{model_id}` | Vision |
| `models remove` | DELETE | `/api/v1/model/{model_id}` | Vision (If-Match) |
| `models capabilities` | GET | `/api/v1/model/{model_id}/capabilities` | Vision |
| `models install` | POST | `/api/v1/model/{model_id}/install` | Vision |
| `models load` | POST | `/api/v1/model/{model_id}/load` | Vision |
| `models unload` | POST | `/api/v1/model/{model_id}/unload` | Vision |
| `models versions` | GET | `/api/v1/model/{model_id}/versions/` | Vision |
| `models instances` | GET | `/api/v1/model/{model_id}/installations/` | Vision |
| `runtimes list` | GET | `/api/v1/runtime/` | Vision |
| `runtimes show` | GET | `/api/v1/runtime/{runtime_id}` | Vision |
| `predict` and task aliases | POST | `/api/v1/predict` | Engine-specific typed request |
| `train` | POST | `/api/v1/train/` | Engine-specific typed request |
| `validate` | POST | `/api/v1/validate/` | Engine-specific typed request |
| `export` | POST | `/api/v1/export/` | Engine-specific typed request |
| `benchmark` | POST | `/api/v1/benchmark/` | Engine-specific typed request |
| `jobs list` | GET | `/api/v1/job/` | Vision |
| `jobs create` | POST | `/api/v1/job/` | Vision |
| `jobs show` | GET | `/api/v1/job/{job_id}` | Vision |
| `jobs cancel` | POST | `/api/v1/job/{job_id}/cancel` | Vision |
| `jobs logs` | GET | `/api/v1/job/{job_id}/logs` | Vision |
| `artifacts show` | GET | `/api/v1/artifact/{artifact_id}` | Vision |
| `artifacts download` | GET | `/api/v1/artifact/{artifact_id}/content` | Vision |
| `executions list` | GET | `/api/v1/execution/` | Vision |
| `executions show` | GET | `/api/v1/execution/{execution_id}` | Vision |
| `executions manifest` | GET | `/api/v1/execution/{execution_id}/manifest` | Vision |
| `executions reproduce` | POST | `/api/v1/execution/{execution_id}/reproduce` | Vision |
| `settings list` | GET | `/api/v1/setting/` | OPAL |
| `settings show/update/remove` | GET/PUT/DELETE | `/api/v1/setting/{key}` | OPAL |
| `health` | GET | `/api/v1/health/` | OPAL |
| `version` | GET | `/api/v1/info/` | OPAL |
| `yolo-cli track` | POST | `/api/v1/track/` | YOLO-only |
| `yolo-cli tune` | POST | `/api/v1/tune/` | YOLO-only |
| `yolo-cli solutions run` | POST | `/api/v1/solution/run` | YOLO-only |

**Important distinction:** The independent model installations endpoint reports only what that engine knows. `opal look models discover` would aggregate model **metadata** across engines and instances; it must never claim to centralize their weights or automatically install models.

## 4. Unified CLI command examples

### Discovery and automatic selection

```bash
opal look plugins discover
opal look plugins list
opal look engines discover
opal look engines list
opal look engines capabilities rfdetr
opal look engines instances yolo
opal look runtimes discover
opal look runtimes list
opal look --engine yolo models list
opal look --engine auto --instance auto detect --source image.jpg
```

An engine family may be available on several hosts. A runtime might support inference only, while a PyTorch model may also support training. A model's task set and the selected runtime's operations must both match the requested task. Missing engines must never prevent other engines from running.

### Engine, instance and overload policy

```bash
# Explicit placement; no implicit fallback
opal look --engine yolo --instance gpu-server \
    predict --model yolo26n.pt --task detect --source image.jpg \
    --fallback none --on-overload reject

# Allow another YOLO instance on transient failure/overload
opal look --engine yolo --instance auto \
    predict --model yolo26n.pt --task detect --source image.jpg \
    --fallback instance --on-overload fallback --timeout-ms 5000

# Cross-family fallback must be explicitly authorized
opal look --engine auto --instance auto \
    predict --model auto --task detect --source image.jpg \
    --fallback engine
```

Training and other state-changing work must never be silently replayed when the first attempt's outcome is unknown. Engine services are responsible for enforcing their bounded queues; Look performs permitted selection and routing, not centralized GPU scheduling.

### Local and remote source handling

```bash
# Local image may be transparently uploaded when engine runs remotely
opal look --engine yolo --instance gpu-server predict \
    --model yolo26n.pt --task detect --source ./frame.jpg

# Explicit upload
opal look --engine dfine predict --model dfine-s --task detect --upload ./frame.jpg

# RTSP may be routed as a network source only when reachable/authorized
opal look --engine rfdetr predict --model nano --task detect \
    --source 'rtsp://camera.example/stream'
```

All remote host-path/URL accesses require access-policy checks. The engine cannot assume a path on the CLI machine is present on the remote server. Uploaded media and remote URL fetching must have size, scheme, authorization and timeout controls.

### Training, validation, export and benchmarking

```bash
# These commands delegate to the selected engine's own REST API
opal look --engine yolo train --model yolo26n.pt \
    --dataset dataset.yaml --epochs 100
opal look --engine rfdetr validate --model nano --dataset validation.yaml
opal look --engine rtdetr export --model rtdetrv2-s --format onnx
opal look --engine dfine benchmark --model dfine-s \
    --device cuda:0 --measure end-to-end

# Common comparable result envelope, independent native metrics
opal look benchmarks compare --runs bench-001,bench-002
```

**Integration note:** Current Look v1.7.1 explicitly excludes training/export from its native application contract. These commands must be routed to the independent engines and formally approved in a future Look CLI/interface migration; they are not currently established Look REST routes.

### Versioned, explicit model lifecycle

```bash
opal look models discover
opal look models list --refresh --include-stale
opal look models instances yolo/yolo26n
opal look models versions yolo/yolo26n
opal look --engine yolo --instance gpu-server \
    models install yolo/yolo26n --version latest
opal look --engine yolo --instance gpu-server \
    models load yolo/yolo26n@1.0
opal look --engine yolo --instance gpu-server \
    models remove yolo/yolo26n@1.0 --dry-run
```

`latest` resolves to a version and hash. Install/remove actions are explicit and affect only the selected engine-owned installation. An active pipeline, loaded model or in-flight job prevents unsafe removal. Discovery caches are metadata only and stale records are not treated as runnable.

### Reusable tracking and video analytics

```bash
opal look trackers list
opal look track --engine rfdetr --tracker bytetrack --source clip.mp4
opal look track --engine yolo --tracker native --source clip.mp4
opal look analytics count --engine yolo --class person --source clip.mp4
opal look analytics heatmap --engine rtdetr --source clip.mp4
opal look solutions run --engine yolo --solution object-counter --source clip.mp4
```

Tracking and analytics are common Look-level operations on normalized results, with optional engine-native workflows. Names such as `native` are resolved through discovery and do not imply a proprietary YOLO tracking algorithm.

### Continuous inference and typed pipelines

```bash
opal look streams create driveway --source rtsp://camera.example/stream \
    --engine yolo --model yolo26n.pt
opal look streams start driveway
opal look streams watch driveway
opal look streams stop driveway

opal look pipelines add driveway --engine yolo --source rtsp://camera.example/stream
opal look pipelines steps add driveway --type detection --id detect
opal look pipelines steps add driveway --type tracking --id tracking --tracker bytetrack
opal look pipelines steps connect driveway --from detect --to tracking
opal look pipelines steps add driveway --type fusion --id fusion --method consensus --min-engines 2
opal look pipelines steps update driveway tracking --on-error retry --max-retries 3
opal look pipelines steps update driveway fusion --merge-policy quorum --min-inputs 2 --timeout-ms 500
opal look pipelines update driveway --buffer-policy drop-oldest --buffer-size 5
opal look pipelines validate driveway
opal look pipelines start driveway
opal look pipelines metrics driveway
```

This is a proposal for **vision-specific DAG processing**. For currently implemented Look APIs, retain existing singular `/api/v1/pipeline/` paths and `/api/v1/session/` SSE lifecycle rather than introducing competing routes because the CLI examples use plural command groups.

### Class taxonomy and geometry

```bash
opal look classes mappings set \
    --engine rtdetr --model pedestrian-detector \
    --class-id 1 --canonical person
opal look classes list
```

Normalized `xyxy` boxes use original orientation-corrected frame pixel coordinates. Canonical taxonomy is optional for standalone inference but necessary for unambiguous cross-engine fusion. Unmapped native classes are preserved.

### Artifacts, manifests and reproducibility

```bash
opal look --engine rfdetr segment --model segmentation-model \
    --source image.jpg --output-mode reference
opal look artifacts download mask-123 --output mask.png
opal look executions show exec-123
opal look executions manifest exec-123 --output execution.yaml
opal look executions reproduce exec-123
```

Reproduction is best effort; it checks access to immutable model/input references and does not promise bitwise deterministic output. The CLI must confirm before re-executing side-effectful actions. Returned manifests must redact secrets.

## 5. CLI-generation invariants

1. **All canonical commands originate from an HTTP operation or an explicit `x-opal-cli.aliases` mapping.** No hidden REST endpoints.
2. `predict --task segment` and `segment` share a single REST prediction request; similarly detect/classify/pose/obb/depth/embed.
3. Dynamic CLI help or pre-execution validation must reflect engine **and** model **and** runtime support. A static command tree may show potential aliases but unsupported calls return clear errors.
4. Use the OPAL kernel's **hyphenated CLI flags**, canonical verbs (`add`, `remove`, `list`, `show`, `update`) and `x-opal-cli` conventions.
5. Propagate four `X-Opal-*` headers; they convey correlation context, never authorization.
6. Mutating configuration requires current strong `If-Match` where specified. Surface 412/428 clearly; do not silently retry conflicting writes.
7. Invalid engine-specific parameters return 422. No silent option dropping.
8. Explicit instance selection implies strict routing unless `--fallback` is supplied.
9. No implicit model download, replacement or deletion; each engine owns its weights and memory.
10. All output operations disclose the actual engine, instance, runtime, model, and execution manifest ID.

## 6. Acceptance checks for the CLI implementation

- [ ] One shared CLI generator can render all four independent trees without hand-editing common commands.
- [ ] A command tree diff detects unintended operations or lost engine extensions.
- [ ] Task aliases dispatch to the same prediction operation.
- [ ] Engine-native YOLO tracking/tuning/solution endpoints are not masquerading as universal operations.
- [ ] A missing RF-DETR/RT-DETR/D-FINE package cannot break available engines.
- [ ] Local and REST-backed plugins disclose the same engine capability contract.
- [ ] Model operations preserve engine ownership and installed-version identity.
- [ ] Typed `engine_options` are validated, including tests that unknown keys fail.
- [ ] Correlation headers, OpalError, auth, ETag preconditions and idempotency are consistent with the real OPAL kernel.
- [ ] Look integration is reviewed against the existing 1.7.1 contract before any update or deployment.

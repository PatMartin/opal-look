![OPAL Look — machine vision for the OPAL ecosystem](opal-look.png)

# OPAL Look
### Give your software eyes. Decide what happens next.

A camera sees movement. An image contains something interesting. A service needs to know **what's in the frame**, not just where the file lives.

That's the job of **OPAL Look**, the vision component of [OPAL](https://github.com/PatMartin/opal): an **API-first image-analysis service** with models, sources, profiles, stored results, snapshots, analysis sessions, a Typer CLI, and a browser console.

~~~text
       Image / uploaded media / configured source
                          │
                          ▼
                     OPAL Look
                   FastAPI REST API
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
        Models          Profiles         Sources
      + engines        + filters      + media catalog
          └───────────────┬────────────────┘
                          ▼
                    Analyze a frame
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
      Structured       Annotated       Persistent
       results         snapshots         history
          └───────────────┬────────────────┘
                          ▼
                  Other OPAL services
               rules, actions, voice, AI
~~~

Think of it as the **eyes** in a modular assistant. [OPAL Listen](https://github.com/PatMartin/opal-listen) hears; [OPAL Look](https://github.com/PatMartin/opal-look) sees; [OPAL Event](https://github.com/PatMartin/opal-event) decides what to do when an event arrives; [OPAL Talk](https://github.com/PatMartin/opal-talk) gives the system a voice. The interfaces are designed to fit together without combining everything into one giant application.

> **Know what works today:** This repository currently ships a **synthetic vision engine**. It generates deterministic, correctly structured results for developing and testing the pipeline; **it does not actually recognize people, vehicles, text, or other objects in your photos**. Image uploads, synthetic analysis, stored results, snapshots, media-backed sessions, and the REST clients are implemented. Real camera/RTSP capture, actual trained-model inference, and video decoding require additional adapters.

## Why OPAL Look?

- **One REST contract for vision.** Define an analysis request once; let a model adapter fulfill it.
- **Five structured analysis tasks.** Detection, classification, segmentation, pose, and OCR all have defined result shapes.
- **Model and engine discovery.** Register resources, inspect capabilities, validate availability, and select a model.
- **Reusable profiles.** Bundle a model, task, confidence threshold, class filters, regions, and other analysis settings.
- **Media as first-class input.** Upload JPEGs or PNGs, reuse their IDs, download originals, and inspect retention.
- **Results with receipts.** Stored detections, timestamps, source and model references, and correlation metadata are discoverable later.
- **Frame-aware snapshots.** Capture a JPEG from the analyzed frame, optionally with annotations, and retain it separately.
- **Session lifecycle.** Start a media-backed analysis session, observe status and results, and stop/delete it through REST.
- **A practical command line.** Typer covers the service as a thin HTTP client; the web app uses the API too.
- **Deliberately bounded work.** Limits on uploads, decoded pixels, concurrent sessions, analysis time, result retention, and event publication.

The philosophy is simple: **the server owns behavior; the CLI and UI are clients**. The [OpenAPI 1.4.0 contract](opal_look_v1.4.0.yaml) describes the intended interface; this README distinguishes the implemented functionality from things still waiting for hardware adapters.

## Installation

### 1. Install the service and CLI

You need **Python 3.12 or newer** and Git. The commands below use Linux/macOS (including Ubuntu and Raspberry Pi OS with a suitable Python version).

~~~bash
git clone https://github.com/PatMartin/opal-look.git
cd opal-look

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
~~~

The repository declares two console commands:

| Command | Purpose |
| --- | --- |
| `opal-look` | Run the FastAPI service |
| `opal-look-cli` | Call its REST API using Typer |

**Source-checkout note:** The current `pyproject.toml` explicitly packages `src/opal_look` but not the sibling `src/opal_look_cli` directory. If `opal-look-cli` fails with `ModuleNotFoundError: opal_look_cli`, expose the source tree while working from the checkout:

~~~bash
export PYTHONPATH="$PWD/src:$PYTHONPATH"
opal-look-cli --help

# Alternative that doesn't depend on the installed script:
python -m opal_look_cli.cli --help
~~~

This is a development workaround, not a claim that wheel packaging is already fixed.

### 2. Start OPAL Look

In terminal one:

~~~bash
opal-look

# Equivalent with uvicorn:
# uvicorn opal_look.app:create_app --factory --host 127.0.0.1 --port 8000
~~~

Open terminal two in the repository directory, activate the virtual environment, and check the API:

~~~bash
source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PYTHONPATH"

opal-look-cli info
opal-look-cli health
opal-look-cli engines list
opal-look-cli models list
opal-look-cli settings show
~~~

Default locations:

<<<<<<< HEAD
The included **synthetic** engine/model is useful for exploring the API and testing the workflow. It is not a trained object detector.

First, upload a local JPEG or PNG:

```bash
opal-look-cli media upload ./example.jpg
```

Copy the `media_id` from the response, then run an analysis against it (replace `YOUR_MEDIA_ID`):

```bash
opal-look-cli analyze run --body '{"media_id":"YOUR_MEDIA_ID","model_id":"synthetic-vision","task":"detection"}'
```

Alternatively, explore uploads, analysis, and results using the [web app](http://127.0.0.1:8000/app/).

### 4. Try an RTSP camera (optional)

RTSP sources decode through PyAV (bundled FFmpeg — no system install needed). Register a camera, validate connectivity, then open a live analysis session:

```bash
opal-look-cli sources add --body '{"source_id":"driveway","name":"Driveway","type":"rtsp","locator":"rtsp://192.168.1.50:554/stream1"}'
opal-look-cli sources validate driveway
opal-look-cli sessions add --body '{"source_id":"driveway","model_id":"synthetic-vision","task":"detection"}'
```

For authenticated cameras, provision credentials out of band before starting the service — never in the locator:

```bash
export OPAL_LOOK_CRED_DRIVEWAY=camera-user:camera-pass
opal-look-cli sources update driveway --body '{"credential_ref":"driveway"}'
```

Live sessions honor `settings.max_fps` analysis pacing and the `reconnect` policy (exponential backoff; exhaustion fails the session). MJPEG preview and SSE result events work the same as for media sessions.

### 5. Run the tests

```bash
python -m pytest
```

**That's it.** You now have the local API, browser UI, and REST CLI available.

## How OPAL Look fits into OPAL

OPAL Look is the vision component of the broader [OPAL project](https://github.com/PatMartin/opal). It handles media inputs and image-analysis workflows. Other OPAL services can consume its results through REST or, when configured, event publication.

The core design is **API-first**: the server owns behavior, persistence, and validation. The Typer CLI and single-page application are clients of the same API rather than separate implementations of the business logic.

## Features

| Area | What it does |
=======
| Service | Address |
>>>>>>> 8bf5d7564b3e59df8389a3564bcd83e8e55be8cf
| --- | --- |
| REST API | `http://127.0.0.1:8000/api/v1/` |
| Web app | `http://127.0.0.1:8000/app/` |
| Health | `http://127.0.0.1:8000/api/v1/health/` |
| Authoritative API specification | [`opal_look_v1.4.0.yaml`](opal_look_v1.4.0.yaml) |

**Note:** The service deliberately disables FastAPI's generated `/docs`, `/redoc`, and `/openapi.json` endpoints. Use the checked-in contract and the running API instead.

**Already running OPAL Listen?** It also commonly uses port 8000. Put Look on port **8002** and point the CLI at it:

~~~bash
# Server terminal:
OPAL_LOOK_PORT=8002 opal-look

# CLI terminal:
opal-look-cli --url http://127.0.0.1:8002 health
~~~

The remainder of this guide assumes the service is on the default port 8000. If you chose 8002, add `--url http://127.0.0.1:8002` immediately after `opal-look-cli` (or use a shell alias).

### 3. Analyze your first image—without a camera or a model download

There's already a PNG in the repository: **`opal-look.png`**, the artwork at the top of this README. Let's use it as our test input.

~~~bash
# Step 1: upload the graphic.
opal-look-cli media upload ./opal-look.png

# The response contains a media_id, like "media-...".
# Step 2: inspect the seeded test model.
opal-look-cli models show synthetic-vision
opal-look-cli models validate synthetic-vision

# Step 3: substitute your actual media_id below.
opal-look-cli analyze run --body '{
  "input": {"kind": "media", "media_id": "YOUR_MEDIA_ID"},
  "model_id": "synthetic-vision",
  "task": "detection"
}'

# Step 4: examine the result history.
opal-look-cli results list
~~~

The generated `result_id` lets you inspect the analysis and capture a snapshot:

~~~bash
opal-look-cli results show YOUR_RESULT_ID

# Run promptly: snapshots need the exact frame still in the short-lived frame cache.
opal-look-cli results snapshot YOUR_RESULT_ID --annotated --out annotated.jpg
~~~

**The labels and boxes are synthetic test output, not real recognition of the poster.** That makes this a useful first test of API routing, storage, filters, result schemas, and snapshot rendering without requiring a GPU or a camera.

### 4. Run the test suite

~~~bash
python -m pytest
~~~

The suite exercises the implemented REST resources, CLI, persistence, analysis, sessions, correlation, and error handling. The service comes with the synthetic adapter, so basic tests don't require a pretrained vision model.

## Complete Typer command tree

This tree follows [`src/opal_look_cli/cli.py`](src/opal_look_cli/cli.py). The actual command is **`opal-look-cli`** (not yet `opal look`). Global flags belong **before** the command/group.

~~~text
opal-look-cli
│  --url URL                                   default http://127.0.0.1:8000
│  --json                                      JSON output
│
├── info
├── health
│
├── engines
│   ├── list
│   ├── show ENGINE_ID
│   ├── add --body JSON | --file PATH           *
│   ├── update ENGINE_ID --body JSON | --file PATH
│   ├── remove ENGINE_ID                        *
│   └── validate ENGINE_ID
│
├── models
│   ├── list
│   ├── show MODEL_ID
│   ├── add --body JSON | --file PATH
│   ├── update MODEL_ID --body JSON | --file PATH
│   ├── remove MODEL_ID
│   └── validate MODEL_ID
│
├── sources
│   ├── list
│   ├── show SOURCE_ID
│   ├── add --body JSON | --file PATH
│   ├── update SOURCE_ID --body JSON | --file PATH
│   ├── remove SOURCE_ID
│   └── validate SOURCE_ID
│
├── profiles
│   ├── list
│   ├── show PROFILE_ID
│   ├── add --body JSON | --file PATH
│   ├── update PROFILE_ID --body JSON | --file PATH
│   ├── remove PROFILE_ID
│   ├── validate PROFILE_ID
│   └── activate PROFILE_ID
│
├── devices
│   └── cameras
│
├── media
│   ├── list [--cursor TOKEN]
│   ├── show MEDIA_ID
│   ├── upload FILE
│   ├── download MEDIA_ID [--out PATH]
│   └── remove MEDIA_ID
│
├── analyze
│   └── run --body JSON | --file PATH
│
├── results
│   ├── list
│   ├── show RESULT_ID
│   ├── add --body JSON | --file PATH           *
│   ├── update RESULT_ID --body JSON | --file PATH *
│   ├── remove RESULT_ID
│   ├── validate RESULT_ID                      *
│   └── snapshot RESULT_ID [--annotated] [--retain] [--out PATH]
│
├── snapshots
│   ├── list
│   ├── show SNAPSHOT_ID
│   ├── add --body JSON | --file PATH           *
│   ├── update SNAPSHOT_ID --body JSON | --file PATH *
│   ├── remove SNAPSHOT_ID
│   └── validate SNAPSHOT_ID                    *
│
├── sessions
│   ├── list [--cursor TOKEN] [--state STATE]
│   ├── show SESSION_ID
│   ├── add --body JSON | --file PATH [--idempotency-key KEY]
│   ├── latest SESSION_ID
│   ├── events SESSION_ID
│   ├── stream SESSION_ID
│   ├── stop SESSION_ID
│   └── remove SESSION_ID
│
├── settings
│   ├── show [KEY]
│   ├── set KEY JSON_VALUE
│   └── unset KEY
│
└── backup
    ├── export
    ├── import --file PATH
    ├── validate [--file PATH]
    ├── list
    ├── create
    ├── download FILENAME [--out PATH]
    ├── restore FILENAME
    └── remove FILENAME
~~~

**`*` Generated CLI commands without a matching server operation:** The current reusable Typer collection builder creates `add`/`remove`/`validate` for every collection. The REST API intentionally does **not** implement all of them. For example, engines cannot be added or removed through REST; results and snapshots are created by analysis and capture, not by generic `add`. Those marked commands are in the CLI tree but **should not be used**. Use the supported workflows below.

~~~bash
opal-look-cli --help
opal-look-cli models --help
opal-look-cli analyze run --help
opal-look-cli sessions add --help
opal-look-cli results snapshot --help

# Target another Look service:
opal-look-cli --url http://127.0.0.1:8002 models list

# Output JSON for scripting:
opal-look-cli --json models list
~~~

**CLI convention:** Configuration catalog verbs are `list`, `show`, `add`, `update`, and `remove`. Operational verbs include `validate`, `activate`, `upload`, `download`, `run`, `snapshot`, and `stop`. The CLI sends REST requests; it does not run inference or access the database directly.

## In-depth CLI guide: useful things to build

### First, learn the objects

| Concept | Think of it as | Example |
| --- | --- | --- |
<<<<<<< HEAD
| `OPAL_LOOK_HOST` | `127.0.0.1` | API bind address |
| `OPAL_LOOK_PORT` | `8000` | API port |
| `OPAL_LOOK_DATA_DIR` | `./data` | Persistent application data directory |
| `OPAL_LOOK_EVENT_TRANSPORT` | Unset | Provisioned ZeroMQ event transport configuration |
| `OPAL_LOOK_CRED_<REF>` | Unset | `user:pass` credentials for a source `credential_ref` (e.g. `OPAL_LOOK_CRED_DRIVEWAY`) |
=======
| **Engine** | A vision implementation | `synthetic` today; plugin adapters later |
| **Model** | A registered resource served by an engine | `synthetic-vision` |
| **Source** | Where frames come from | Uploaded media, camera, RTSP, HTTP, host video |
| **Media** | An uploaded image with an ID and retention | `media-...` |
| **Profile** | A reusable model + task + filter recipe | "Detect people at the front door" |
| **Analysis** | One frame analyzed immediately | `analyze run` |
| **Result** | A structured analysis record | `result-...` |
| **Snapshot** | Exact-frame JPEG, optionally annotated | `snap-...` |
| **Session** | A managed analysis lifecycle for a source | `session-...` |
>>>>>>> 8bf5d7564b3e59df8389a3564bcd83e8e55be8cf

A **source can be registered without being available**. In the current implementation, uploaded-image-backed `media` sources are usable; physical camera/RTSP/HTTP and video-file sources are not yet backed by operational capture/decoding adapters.

### Use case 1: Make an upload-analyze-inspect script

First install [`jq`](https://jqlang.github.io/jq/) if you want the shell to extract IDs automatically. Then run this **from the repository root** against the running service:

~~~bash
# Upload the repo artwork and capture the server-generated ID.
MEDIA_ID=$(opal-look-cli --json media upload ./opal-look.png | jq -r .media_id)
echo "Uploaded: $MEDIA_ID"

# Run a synthetic detection analysis; capture the result.
RESULT_ID=$(
  opal-look-cli --json analyze run --body \
    "{\"input\":{\"kind\":\"media\",\"media_id\":\"$MEDIA_ID\"},\"model_id\":\"synthetic-vision\",\"task\":\"detection\"}" \
  | jq -r .result_id
)
echo "Result: $RESULT_ID"

# Read it back from persistence.
opal-look-cli results show "$RESULT_ID"

# Export an annotated JPEG while the exact frame remains cached.
opal-look-cli results snapshot "$RESULT_ID" \
  --annotated --out ./first-result.jpg
~~~

<<<<<<< HEAD
- The built-in synthetic engine demonstrates flows but does not perform real trained-model inference. Additional engine adapters are needed for real model inference.
- RTSP sources are supported through the PyAV capture adapter (with live sessions, reconnect backoff, and single-frame analyze). Camera devices, HTTP/MJPEG feeds, and host_video decoding still require additional source adapters; configuring such a source does not by itself guarantee a usable feed.
- Some SSE replay-window edge cases and operational counters remain deferred.
=======
No external images, pretrained model, RTSP camera, or shell-side image processing required. You have exercised the **upload → selection → inference adapter → result → snapshot** path.
>>>>>>> 8bf5d7564b3e59df8389a3564bcd83e8e55be8cf

A normal result includes the model, engine, task, timestamps, image dimensions, and task-specific payload. An unstored result can still be returned immediately, but it won't appear in persistent result history.

### Use case 2: Explore five different analysis contracts

A real vision backend may eventually support only some tasks. The synthetic adapter supports **all five** so integrations can be built early:

~~~bash
# Reuse MEDIA_ID from the previous example.
for TASK in detection classification segmentation pose ocr; do
  echo "=== $TASK ==="
  opal-look-cli analyze run --body \
    "{\"input\":{\"kind\":\"media\",\"media_id\":\"$MEDIA_ID\"},\"model_id\":\"synthetic-vision\",\"task\":\"$TASK\"}"
done
~~~

| Task | Expected result shape | Example future use |
| --- | --- | --- |
| `detection` | Objects, labels, confidence, normalized boxes | Person at a front door |
| `classification` | Ranked class labels and confidence | Categorize a frame |
| `segmentation` | Instance masks or a semantic map | Separate foreground from background |
| `pose` | Keypoints, boxes, skeleton metadata | Interpret body position |
| `ocr` | Text regions, polygons, confidence | Read a label or sign |

The **current synthetic outputs are generated test data**. They prove that the payload and filters work, not that the image contains those objects or words.

Want to exercise semantic segmentation specifically?

~~~bash
opal-look-cli analyze run --body \
  "{\"input\":{\"kind\":\"media\",\"media_id\":\"$MEDIA_ID\"},\"model_id\":\"synthetic-vision\",\"task\":\"segmentation\",\"settings\":{\"segmentation_kind\":\"semantic\"}}"
~~~

### Use case 3: Filter the noise to the things that matter

A model might detect several object classes, but your workflow may only care about people in a defined region. Filters are **portable settings**, applied after the inference adapter returns its raw predictions.

~~~bash
opal-look-cli analyze run --body \
  "{\"input\":{\"kind\":\"media\",\"media_id\":\"$MEDIA_ID\"},\"model_id\":\"synthetic-vision\",\"task\":\"detection\",\"settings\":{\"confidence\":0.7,\"class_labels\":[\"person\"]}}"
~~~

For a reusable polygonal region, save a request file:

~~~bash
cat > filtered-analysis.json <<'JSON'
{
  "input": {"kind": "media", "media_id": "REPLACE_WITH_YOUR_MEDIA_ID"},
  "model_id": "synthetic-vision",
  "task": "detection",
  "settings": {
    "confidence": 0.6,
    "class_labels": ["person"],
    "regions": [
      {
        "region_id": "front_door",
        "polygon": [
          {"x": 0.20, "y": 0.10},
          {"x": 0.85, "y": 0.10},
          {"x": 0.85, "y": 0.95},
          {"x": 0.20, "y": 0.95}
        ]
      }
    ]
  }
}
JSON

# Replace the placeholder in that file with an actual uploaded media_id.
opal-look-cli analyze run --file filtered-analysis.json
~~~

Coordinates range from **0 to 1** across the image. A detection passes the polygon test when the **center of its bounding box** lies inside the region. This is a useful way to prototype a driveway-only or doorway-only rule without tying the rest of the system to a particular model.

**No tracking in single-frame mode:** `"tracking": true` is intentionally rejected for `analyze run`. It's a session-oriented concept.

### Use case 4: Define an analysis profile you can reuse

Profiles stop you from repeating the same model, task, and filtering settings in every call.

~~~bash
opal-look-cli profiles add --body '{
  "name": "Front door prototype",
  "model_id": "synthetic-vision",
  "task": "detection",
  "settings": {
    "confidence": 0.65,
    "class_labels": ["person"]
  }
}'

opal-look-cli profiles list

# Use the numeric profile_id returned above:
opal-look-cli profiles show YOUR_PROFILE_ID
opal-look-cli profiles validate YOUR_PROFILE_ID
opal-look-cli profiles activate YOUR_PROFILE_ID
~~~

Once a profile is active, a one-frame request can omit `model_id` and `task`:

~~~bash
opal-look-cli analyze run --body \
  "{\"input\":{\"kind\":\"media\",\"media_id\":\"$MEDIA_ID\"}}"
~~~

The service resolves the active profile, or you can specify `"profile_id": 1` in an analysis body. Request settings can override selected profile defaults; engine-specific options live under `settings.engine_options`.

You can edit a profile with a partial patch:

~~~bash
opal-look-cli profiles update YOUR_PROFILE_ID \
  --body '{"settings":{"confidence":0.8,"class_labels":["person"]}}'
~~~

**Note:** When `settings` is supplied on a profile update, it is a new settings object; re-send the values you still want to preserve rather than assuming a deep per-key merge.

### Use case 5: Turn an uploaded photo into a reusable source

A `media` source is a named way to reference an uploaded image. Unlike a live camera source, it **works with the current implementation**.

~~~bash
# Create a named source for the already-uploaded image.
opal-look-cli sources add --body \
  "{\"source_id\":\"demo-poster\",\"name\":\"README poster\",\"type\":\"media\",\"locator\":\"$MEDIA_ID\"}"

opal-look-cli sources list
opal-look-cli sources show demo-poster
opal-look-cli sources validate demo-poster

# Analyze by source rather than by media ID.
opal-look-cli analyze run --body '{
  "input": {"kind": "source", "source_id": "demo-poster"},
  "model_id": "synthetic-vision",
  "task": "classification"
}'
~~~

The source points to a **media record**, not a copied image. If that media expires or is deleted, the source may remain registered but become unavailable.

To save a fresh copy of the original locally:

~~~bash
opal-look-cli media download "$MEDIA_ID" --out restored-poster.png
opal-look-cli media show "$MEDIA_ID"
opal-look-cli media list
~~~

### Use case 6: Create a managed analysis session

A one-shot analysis returns immediately when inference completes. A **session** has its own identity, state, latest result, history, and lifecycle endpoints.

A media-backed session processes its image and normally completes quickly:

~~~bash
opal-look-cli sessions add --body '{
  "source_id": "demo-poster",
  "model_id": "synthetic-vision",
  "task": "detection",
  "store_results": true
}'

# Copy the returned session_id:
opal-look-cli sessions show YOUR_SESSION_ID
opal-look-cli sessions latest YOUR_SESSION_ID
opal-look-cli sessions list --state completed

# Inspect the results, including those from the session.
opal-look-cli results list
~~~

Sessions start with HTTP **202 Accepted**, transition through the worker, and normally end as `completed` for one uploaded image. If `sessions latest` initially says the result is unavailable, poll `sessions show` until the session has produced a frame.

Use `--idempotency-key` if your client could retry the same start request:

~~~bash
opal-look-cli sessions add \
  --idempotency-key demo-poster-once \
  --body '{"source_id":"demo-poster","model_id":"synthetic-vision","task":"detection"}'
~~~

Reusing the same key **with the same body** can return the original session; reusing it for a different body is a conflict.

The CLI also exposes:

~~~bash
opal-look-cli sessions events YOUR_SESSION_ID
opal-look-cli sessions stream YOUR_SESSION_ID
opal-look-cli sessions stop YOUR_SESSION_ID
opal-look-cli sessions remove YOUR_SESSION_ID
~~~

A session must be terminal before it can be removed. The current CLI uses buffered HTTP reads for `events` and `stream`, so do not depend on those commands for interactive long-running SSE monitoring. For real-time consumption in a future live-source adapter, use an SSE-capable HTTP client against the server endpoints.

### Use case 7: Save evidence as annotated snapshots

After an analysis, the server keeps the **exact analyzed frame in a short-lived cache**. You can render a snapshot with its bounding boxes or other supported annotations.

~~~bash
# Immediate one-off JPEG, written to the local file:
opal-look-cli results snapshot YOUR_RESULT_ID \
  --annotated --out ./annotated.jpg

# Create a separately retained snapshot resource instead:
opal-look-cli results snapshot YOUR_RESULT_ID \
  --annotated --retain

# Inspect the retained resource by snapshot_id from the response:
opal-look-cli snapshots list
opal-look-cli snapshots show YOUR_SNAPSHOT_ID
~~~

For a retained snapshot, use REST to download the JPEG:

~~~bash
curl -fS \
  http://127.0.0.1:8000/api/v1/snapshots/YOUR_SNAPSHOT_ID/content \
  -o retained-snapshot.jpg
~~~

**Two clocks matter:** the frame cache lasts only `frame_cache_seconds` (default **30 seconds**); persistent result metadata lasts `result_retention_hours` (default **168 hours**). A stored `result_id` does not guarantee the original pixels are still available for a new snapshot tomorrow. Capture promptly, or retain a snapshot.

### Use case 8: Build toward an RTSP camera without pretending it's live

The API lets you register a camera or network source. It validates the locator and supported options. That is useful configuration work **even before** the capture adapter exists.

~~~bash
opal-look-cli devices cameras

opal-look-cli sources add --body '{
  "source_id": "front-door",
  "name": "Front door RTSP",
  "type": "rtsp",
  "locator": "rtsp://192.0.2.10:554/stream1",
  "source_options": {"transport": "tcp"}
}'

opal-look-cli sources show front-door
opal-look-cli sources validate front-door
~~~

The `192.0.2.10` address is a documentation-only example; replace it with your camera's host and RTSP path. **Do not put usernames and passwords in the locator URL**—the validator rejects inline credentials. There is a separate `credential_ref` field in the contract for credentials provisioned elsewhere.

**Current result:** a registered RTSP source normally reports `"available": false`, with a message that a network source hasn't been probed. Starting analysis or a session against it returns an unavailable response. The same is true for physical camera capture and video-file decoding today. The **API shape is there**; operational frame adapters are the next implementation step.

Once actual live capture exists, session preview is designed around `GET /api/v1/sessions/{session_id}/preview` (MJPEG), with result/event streams beside it. Do not mistake the presence of these endpoints for a functional live feed in this release.

### Use case 9: Experiment with a custom synthetic model

You can register models that reference installed engine adapters. Here's an intentionally **synthetic** model for deterministic regression experiments:

~~~bash
opal-look-cli models add --body '{
  "model_id": "synthetic-workshop",
  "name": "Workshop test model",
  "engine_id": "synthetic",
  "resource": {"ref": "builtin"}
}'

opal-look-cli models show synthetic-workshop
opal-look-cli models validate synthetic-workshop

# Deterministic output, useful for testing client code:
opal-look-cli analyze run --body \
  "{\"input\":{\"kind\":\"media\",\"media_id\":\"$MEDIA_ID\"},\"model_id\":\"synthetic-workshop\",\"task\":\"detection\",\"settings\":{\"engine_options\":{\"seed\":42}}}"
~~~

The synthetic model supports three example class labels (`person`, `car`, `dog`), plus task-shaped segmentation, pose, and OCR outputs. It does **not** learn from the photo. The `seed` option helps reproduce a predictable inference payload for testing.

Third-party trained adapters can be registered through the Python `opal_look.engines` entry-point mechanism. An actual YOLO or other model adapter must be implemented and installed separately; this repo does not currently include one.

### Use case 10: Search and inspect results later

~~~bash
opal-look-cli results list
opal-look-cli results show YOUR_RESULT_ID
opal-look-cli media list
opal-look-cli snapshots list
opal-look-cli sessions list
~~~

The REST result list supports richer filters than the current Typer wrapper exposes. For example:

~~~bash
# Find recent stored detection results.
curl -fSG http://127.0.0.1:8000/api/v1/results/ \
  --data-urlencode 'task=detection' \
  --data-urlencode 'model_id=synthetic-vision' \
  --data-urlencode 'limit=20'

# Find OCR records containing particular text (synthetic test results).
curl -fSG http://127.0.0.1:8000/api/v1/results/ \
  --data-urlencode 'task=ocr' \
  --data-urlencode 'text=EXIT'
~~~

Results, media, sessions, and snapshots use **opaque cursor pagination**. If a response includes `next_cursor` and `has_more=true`, pass that cursor for the next page. Do not try to calculate a cursor from an ID.

Stored results can be deleted:

~~~bash
opal-look-cli results remove YOUR_RESULT_ID
~~~

Storage retention is intentional: media (default 24 hours), results (168 hours), and retained snapshots (168 hours) are not a permanent evidence vault. Make long-term retention a separate, explicitly managed system.

### Use case 11: Change one setting without hand-editing the server

~~~bash
opal-look-cli settings show
opal-look-cli settings show max_upload_bytes
opal-look-cli settings show frame_cache_seconds

# Give clients more time to request exact-frame snapshots.
opal-look-cli settings set frame_cache_seconds 120

# Allow at most two admitted nonterminal sessions at once.
opal-look-cli settings set max_concurrent_sessions 2

# Return to the schema default for a single overridden setting.
opal-look-cli settings unset frame_cache_seconds
~~~

The value argument is parsed as **JSON**:

~~~bash
opal-look-cli settings set max_preview_fps 3.0
opal-look-cli settings set events_enabled false
~~~

Configuration mutations use **`If-Match` / revision checks** so a concurrent change can be rejected instead of silently overwritten. The CLI fetches revision headers for its supported mutation commands.

A selection of important settings:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `frame_cache_seconds` | 30 | Snapshot window for exact analyzed frame |
| `media_retention_hours` | 24 | Uploaded-media retention |
| `result_retention_hours` | 168 | Stored-result retention |
| `snapshot_retention_hours` | 168 | Retained-snapshot retention |
| `max_concurrent_sessions` | 4 | Session admission limit |
| `max_analysis_timeout_seconds` | 60 | Single analysis timeout |
| `max_preview_fps` | 5 | Preview rate limit |
| `max_upload_bytes` | 1,073,741,824 | Maximum upload size; image decoding has a separate pixel cap |
| `events_enabled` | false | External event publication, when transport is provisioned |

### Use case 12: Back up your experiments before changing configurations

~~~bash
# Check current logical configuration.
opal-look-cli backup validate

# Export as JSON into a local file:
opal-look-cli backup export > look-config.json

# Validate that export without changing the service:
opal-look-cli backup validate --file look-config.json

# Make a server-managed JSON backup.
opal-look-cli backup create
opal-look-cli backup list
~~~

Download the actual filename shown by `backup list`:

~~~bash
opal-look-cli backup download YOUR_BACKUP_FILENAME --out ./look-backup.json
~~~

To re-import a full configuration export:

~~~bash
# WARNING: imports replace configuration; don't execute until ready.
opal-look-cli backup import --file look-config.json
~~~

Or restore a managed backup already on the server:

~~~bash
opal-look-cli backup restore YOUR_BACKUP_FILENAME
~~~

These are **logical configuration backups** (engine/model/source/profile/settings metadata), not an archive of all uploaded images, generated JPEGs, and other stored media. An import/restore is a configuration mutation, so check it first and keep your own copy.

### Use case 13: Prepare for a whole-OPAL vision automation

Here's the intended end-to-end architecture:

~~~text
     Real trained vision adapter (future installation)
                         │
              Camera frame / image
                         │
                     OPAL Look
                  result + snapshot
                         │
             Optional event publication
                         │
                     OPAL Event
                rule / action decision
                         │
               ┌─────────┴──────────┐
               ▼                    ▼
           OPAL Talk            OPAL Think
     "A visitor arrived."    analyze / plan
~~~

A good integration separates four concerns:

1. **Perception:** Look produces a structured result, not a direct physical command.
2. **Selection:** A rule or agent decides which results are relevant.
3. **Action:** Event executes an explicitly configured shell/HTTP/Python action.
4. **Feedback:** Talk or another service communicates what happened.

**Publication caveat:** `events_enabled` is **false by default** and requires `OPAL_LOOK_EVENT_TRANSPORT` provisioned at server startup. The current publisher/event-topic wiring also needs integration verification against OPAL Event before treating automatic event delivery as ready for production. REST polling of stored results is the straightforward working integration path today.

The point is to **build the interface now, prove the workflow with synthetic data, then swap in a real inference and capture adapter** without rewriting your CLI, browser client, or downstream consumer.

## How the pieces fit together

~~~text
     opal-look-cli (Typer)           Browser console (/app/)
               │                             │
               └───────────┬─────────────────┘
                           ▼
                       FastAPI REST
                  /api/v1/... endpoints
                           │
     ┌─────────────────────┼─────────────────────────┐
     ▼                     ▼                         ▼
 Config repositories     Workflows                 Settings
 engines/models/        analyze/session            + limits
 profiles/sources        + snapshots
     │                     │
     └─────────┬───────────┘
               ▼
       EngineAdapter registry
               │
               ▼
      Synthetic engine (built in)
      Custom plugins (if installed)
               │
               ▼
        SQLite + media files
~~~

- **REST first:** Routes own validation, selection, task handling, and resource lifecycles.
- **Repositories + unit of work:** Per-aggregate persistence APIs sit behind a SQLite-backed store; configuration writes use transactions and revision checks.
- **Engine adapters:** The built-in synthetic engine implements the adapter protocol and provides deterministic test payloads; plugin discovery supports future real implementations.
- **Explicit input types:** An analysis request names an uploaded `media` object or a configured `source`.
- **Short-lived frame cache:** Results keep metadata; snapshots capture actual image pixels while available.
- **OPAL correlation headers:** Middleware manages request/session/transaction correlation independently of application payloads.
- **Optional ZeroMQ events:** Best-effort publication is separate from inference and off unless enabled.
- **Browser client:** The static SPA lives under `src/opal_look/static/` and calls REST rather than having its own analysis engine.

The full intended contract is [`opal_look_v1.4.0.yaml`](opal_look_v1.4.0.yaml). The implemented Python package is currently version **0.1.0**; those are separate identifiers (contract vs implementation).

## Current capabilities and limitations

| Capability | Current status |
| --- | --- |
| Upload and inspect JPEG/PNG | Implemented |
| Synthetic detection/classification/segmentation/pose/OCR | Implemented (test data, not true recognition) |
| Persist/search result metadata | Implemented |
| Exact-frame annotated snapshots | Implemented while frame is cached |
| Media-backed, single-image sessions | Implemented |
| Session status, latest result, SSE/MJPEG endpoints | Implemented, with finite-media and buffering limitations |
| Register RTSP/HTTP/camera/video source configurations | Implemented |
| Capture actual live RTSP/USB/HTTP frames | **Not yet implemented** |
| Decode uploaded/host video files | **Not yet implemented** |
| Discover attached cameras | No capture discovery adapter installed |
| YOLO/other trained inference | Requires an additional engine adapter |
| Event-driven OPAL integration | Optional/experimental; transport and topic compatibility need verification |

**Practical consequence:** registering an RTSP URL doesn't make it playable. A useful first hardware milestone is implementing a capture adapter, then adding a trained model adapter, then validating preview, annotations, session lifecycle, and event publication end-to-end.

## Troubleshooting

| What happened? | What to check |
| --- | --- |
| `opal-look-cli` cannot import its module | Add the checkout's `src/` to `PYTHONPATH` (see Installation) |
| Connection refused | Start `opal-look`; confirm port 8000 (or your overridden port) |
| OPAL Listen also uses port 8000 | Run Look on 8002, use CLI `--url` |
| `/docs` returns 404 | Generated docs are disabled; use the checked-in OpenAPI file |
| Analysis returns 422 | Include required `input` object and a valid model/task |
| Result is full of surprising boxes | The current engine is **synthetic**, not image understanding |
| RTSP session returns 503 | Live capture adapter isn't implemented |
| Snapshot says frame unavailable | Capture before the short frame-cache expiry |
| Configuration change returns 412/428 | Revision / `If-Match` precondition; reload and retry |
| Can't enable events | Provision transport first; external integration still needs verification |

## Development and testing

~~~bash
# From the repository root:
python -m pip install -e ".[dev]"
python -m pytest

# Alternate service startup:
uvicorn opal_look.app:create_app --factory \
  --host 127.0.0.1 --port 8000

# Focus the test run:
python -m pytest tests/test_analyze.py tests/test_sessions.py
python -m pytest tests/test_cli.py tests/test_media.py
~~~

When extending the project, keep the [OpenAPI contract](opal_look_v1.4.0.yaml) aligned with server behavior, preserve the REST-only CLI design, add regression tests for each capability, and make small reviewable commits. Contributor design conventions and known deferrals are recorded in [`AGENTS.md`](AGENTS.md).

### Repository map

~~~text
opal-look/
├── opal-look.png                  top-level project graphic
├── README.md                      this guide
├── opal_look_v1.4.0.yaml          authoritative OpenAPI contract
├── pyproject.toml                 Python package / entry points
├── AGENTS.md                      architecture and contributor conventions
├── src/
│   ├── opal_look/
│   │   ├── app.py                FastAPI application factory
│   │   ├── analysis.py           single-image analysis workflow
│   │   ├── sessions.py           managed session worker
│   │   ├── engines.py            synthetic adapter + plugin registry
│   │   ├── sources.py            source validation / availability
│   │   ├── media.py              image validation / decoding
│   │   ├── snapshots.py          annotation / retention helpers
│   │   ├── settings.py           service settings
│   │   ├── events.py             optional event publication
│   │   ├── repositories/         per-resource data access
│   │   ├── routers/              REST API endpoints
│   │   └── static/               bundled browser console
│   └── opal_look_cli/
│       ├── cli.py                Typer command tree
│       └── client.py             REST client
└── tests/                         API, CLI, session, analysis, storage tests
~~~

---

**OPAL Look is where pixels become structured possibilities.** Start with an uploaded image. Learn the result format. Give it a profile, a snapshot, and a session. Then add the real camera and inference adapters when you're ready to turn those possibilities into useful observations.

[OPAL](https://github.com/PatMartin/opal) · [OPAL Event](https://github.com/PatMartin/opal-event) · [OPAL Listen](https://github.com/PatMartin/opal-listen) · [OPAL Talk](https://github.com/PatMartin/opal-talk) · [OPAL Think](https://github.com/PatMartin/opal-think)

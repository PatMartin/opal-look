![OPAL Look — machine vision for the OPAL ecosystem](opal-look.png)

# OPAL Look
### Give your software eyes. Keep the decisions yours.

A camera sees a driveway. A photo lands in a folder. A robot wonders whether the path ahead is clear. In each case, the interesting question is not *where are the pixels?* but **what can we observe, and what should happen next?**

**OPAL Look** is the visual observation service in [OPAL](https://github.com/PatMartin/opal). It decodes RTSP camera feeds into live video (MJPEG), single-frame snapshots, and per-frame detection events (SSE) — with optional pluggable inference engines for object detection — through a REST API, a Typer command-line client, and a browser console.

~~~text
              RTSP camera / still image
                        |
                        v
                EPHEMERAL STREAM
             (one decode, fanned out)
             |          |          |
             v          v          v
          MJPEG      snapshot    SSE events
          video      (JPEG)     (frame/detection/status)
                        |
                  ENGINE (optional)
              synthetic / plugin adapters
                        |
                        v
             detections + annotated overlays
~~~

**Engine-free core.** Video streams run with zero AI engines installed. An engine — the built-in `synthetic` adapter or a plugin registered via the `opal_look.engines` entry point — adds `predict` for still images and inference-mode streams with detection events and bounding-box overlays.

> **What is real today?** OPAL Look includes a deterministic **synthetic inference engine** for testing the API, not a trained object detector. It **does not identify people, cars, or animals in actual photographs**. Real RTSP decode is implemented with PyAV (`av`, installed by default — without it, stream admission answers `503`). A real detector needs an engine adapter (e.g. Ultralytics YOLO, RF-DETR); see [Engine plugins](#engine-plugins).

**Explore:** [Quickstart](#quickstart-in-five-minutes) · [Building blocks](#understand-the-building-blocks) · [CLI reference](#complete-cli-reference) · [Watching live video](#watching-live-video) · [REST map](#rest-map) · [Configuration](#configuration-and-security) · [Limitations](#current-capabilities-and-known-limitations) · [Contributing](#tests-contract-and-contributing)

---

## Quickstart in five minutes

### 1. Install from a checkout

You need **Python 3.12+**. The commands below use Bash. Windows users can create a venv with `py -3.12 -m venv .venv` and run `.venv/Scripts/pip` and `.venv/Scripts/python` directly.

~~~bash
git clone https://github.com/PatMartin/opal-look.git
cd opal-look
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
~~~

### 2. Start the service

~~~bash
opal serve            # or: python -m opal_look
~~~

Look listens at **http://127.0.0.1:8000** on loopback by default. In a second terminal (same venv):

~~~bash
opal-look info health
opal-look engine list
opal-look model list
~~~

`opal` and `opal-look` are the same REST client — `opal look info health` works identically. The browser console lives at **http://127.0.0.1:8000/app/**. To use another port: `OPAL_LOOK_PORT=8002 opal serve`, then `opal-look --url http://127.0.0.1:8002 info health`.

### 3. Detect objects in a still image

The bundled `synthetic` engine ships one model, `synthetic-det`. Load it, then predict against any local JPG/PNG:

~~~bash
opal-look model load synthetic-det --engine synthetic
opal-look predict image --engine synthetic --model synthetic-det --source sample.jpg
~~~

The result is **structured, deterministic detection-shaped output** — synthetic labels, not facts about the photo. That's intentional: you can exercise the whole REST/CLI surface before committing to a model provider.

### 4. Watch a live camera

~~~bash
opal-look stream start rtsp://192.168.1.20:554/stream1 --name front
opal-look stream watch front          # SSE: frame/status events, Ctrl-C to detach
opal-look stream snapshot front --out front.jpg
opal-look stream metrics front
opal-look stream stop front
~~~

`--name` pins the stream id so every URL is predictable (`/api/v1/stream/front/...`). Omit it and the server generates a `strm_*` id. A name conflict with a *live* stream gets a `409`; once the holder stops, the name is free to reuse.

---

## Understand the building blocks

| Resource | What it represents | Why you care |
|---|---|---|
| **Streams** | Ephemeral RTSP sessions: one decode, fanned to MJPEG/SSE/snapshot consumers | Live video and detection events; gone on restart |
| **Engines** | Inference adapters (`synthetic` built-in; plugins via entry points) | Optional AI: predict + inference-mode streams |
| **Models** | Engine-federated metadata (`synthetic-det`, …) | Load/unload per engine before inference |
| **Hardware** | Engine-local execution devices | Choose a device for inference |
| **Profiles** | Named config bundles stored verbatim; one active at a time | Record the deployment posture clients should honor |
| **Settings** | Global service knobs (limits, buffers, caps) | Tune admission limits, upload sizes |
| **Backup** | Portable config export/validate/import + managed archives | Move or restore a deployment |

**Contract:** `openapi/opal_look_v1.7.1.yaml` (+ `openapi/shared/opal_kernel.yaml`) is the authoritative contract — pinned, never generated. Amendments go upstream first; see `specs/` for the migration ledger and pending amendments.

---

## Complete CLI reference

There are **three executables**:

- `opal` — OPAL suite umbrella: `opal serve` starts the service, `opal look …` runs client commands.
- `opal-look` — the same REST client directly.
- `opal-look-audit` — offline contract audit (see [Tests & contract](#tests-contract-and-contributing)).

### Global flags and common patterns

~~~bash
opal-look --help
opal-look --url http://127.0.0.1:8002 --json stream list
opal-look stream --help
opal-look config profile add --file profile.json
~~~

| Flag | Usage |
|---|---|
| `--url URL` | Server base URL; default `http://127.0.0.1:8000` |
| `--json` | JSON output for scripts and `jq` |
| `--body 'JSON'` | Inline request object |
| `--file FILE` | Load a JSON request object from disk |
| `--out FILE` | Save returned binary data |
| `--name NAME` | Client-chosen stream id on `stream start` |

Put global flags **before the command group**. The CLI fetches ETags and sends `If-Match` automatically on config mutations.

### The command tree

~~~text
opal-look [--url] [--json]
|-- tree [--ascii]
|-- engine
|   |-- list
|   |-- show ENGINE_ID
|   |-- discover
|   `-- capabilities ENGINE_ID
|-- model
|   |-- list [--engine]
|   |-- show MODEL_ID [--engine]
|   |-- load MODEL_ID [--engine]
|   `-- unload MODEL_ID [--engine]
|-- predict
|   `-- image --engine --model --source [--confidence] [--device] [--options] [--include-native]
|-- hardware
|   |-- list [--engine]
|   `-- show DEVICE_ID [--engine]
|-- stream
|   |-- start SOURCE [--name] [--engine] [--model] [--confidence] [--device]
|   |           [--options] [--annotate] [--buffer-policy] [--buffer-size]
|   |-- list
|   |-- show STREAM_ID
|   |-- stop STREAM_ID
|   |-- watch STREAM_ID
|   |-- watch-video STREAM_ID [--out] [--annotated] [--max-bytes]
|   |-- snapshot STREAM_ID [--out] [--annotated]
|   `-- metrics STREAM_ID
|-- info
|   |-- health
|   |-- live
|   |-- ready
|   |-- version
|   `-- ping
|-- backup
|   |-- list
|   |-- create
|   |-- download FILENAME [--out]
|   |-- restore FILENAME
|   |-- remove FILENAME
|   |-- export
|   |-- import [--file] [--body]
|   `-- validate [--body] [--file]
|-- service
|   |-- start [--append] [--port] [--host] [--data-dir]
|   |-- stop
|   `-- log [--lines]
|-- config
|   |-- engine update ENGINE_ID [--body] [--file]
|   |-- profile list|show|add|update|remove|activate
|   `-- setting list|show|update|patch|set|remove
`-- setting
    |-- get KEY
    `-- delete KEY
~~~

### Quick task lookup

| Your goal | CLI command |
|---|---|
| Is Look running? | `info ready` |
| What engines are installed? | `engine list` |
| What models can I load? | `model list` |
| Detect in a photo | `predict image --engine E --model M --source img.jpg` |
| Start a camera stream | `stream start rtsp://cam/feed --name front` |
| Live detection events | `stream watch front` |
| Save a frame | `stream snapshot front --out frame.jpg` |
| Capture video to a file | `stream watch-video front --out front.mjpeg --max-bytes 5000000` |
| Change a setting | `config setting set max_concurrent_streams 8` |
| Export configuration | `backup export` |
| Tail the service log | `service log --lines 20` |

---

## Watching live video

`GET /api/v1/stream/{id}/video` serves `multipart/x-mixed-replace` MJPEG, decoded **once per stream** and fanned out — viewers never open a second camera connection.

- **Browser / SPA:** open `http://127.0.0.1:8000/app/` (streams → video), or hit the video URL directly in a tab.
- **VLC:** `vlc http://127.0.0.1:8000/api/v1/stream/front/video`
- **ffplay/ffmpeg:** `ffplay -f mpjpeg http://127.0.0.1:8000/api/v1/stream/front/video`

Add `?annotated=true` on an inference stream started with `annotate=true` for the bounding-box overlay feed.

---

## Configuration and security

Environment variables (a repo-root `.env` is loaded automatically; real env vars win):

| Variable | Purpose |
|---|---|
| `OPAL_LOOK_HOST` / `OPAL_LOOK_PORT` | Bind address (default `127.0.0.1:8000`) |
| `OPAL_LOOK_DATA_DIR` | Data directory (default `./data`) |
| `OPAL_LOOK_TOKEN` | Bearer token. **Set** → every `/api/v1` call needs `Authorization: Bearer <token>`. **Unset** → loopback dev mode; non-loopback binds are refused |
| `OPAL_LOOK_CRED_<REF>` | RTSP credentials (`user:pass`) injected at connect time; never stored, logged, or echoed |

The CLI picks up `OPAL_LOOK_TOKEN` automatically. RTSP URIs with embedded credentials are always redacted in API output (`source_redacted`).

### Engine plugins

Engines self-register through the `opal_look.engines` Python entry-point group by implementing the `EngineAdapter` protocol (`capabilities`, `models`, `load_model`, `predict`, `hardware`, …). The `synthetic` adapter is the reference implementation — deterministic detections with no ML dependencies. Capture backends similarly plug into `opal_look.capture` (`RtspAvAdapter` decodes via PyAV).

---

## REST map

| Surface | Endpoint |
|---|---|
| Health / info | `GET /`, `/health`, `/api/v1/health/`, `/api/v1/info/*` |
| Settings | `GET/PATCH /api/v1/setting/`, per-key `GET/PUT/DELETE /api/v1/setting/{key}` |
| Engines | `GET /api/v1/engine/`, `PATCH /api/v1/engine/{id}`, `POST …/discover`, `GET …/capabilities` |
| Hardware | `GET /api/v1/hardware/`, `/api/v1/hardware/{id}` |
| Models | `GET /api/v1/model/`, `/api/v1/model/{id}`, `POST …/load`, `…/unload` |
| Predict | `POST /api/v1/predict` |
| Profiles | `GET/POST /api/v1/profile/`, `{id}` CRUD, `POST …/activate` |
| Streams | `POST/GET /api/v1/stream/`, `{id}`, `…/stop`, `…/events` (SSE), `…/video` (MJPEG), `…/snapshot`, `…/metrics` |
| Backup | `POST /api/v1/backup/export|validate|import`, `create`, `list`, `download`, `restore`, `delete` |
| Service | `POST /api/v1/service/start|stop`, `GET /api/v1/service/log` |

Config mutations require `If-Match` on the global config revision (the CLI handles it); `POST /api/v1/stream/` accepts `Idempotency-Key` for safe admission retries.

---

## Current capabilities and known limitations

- **Streams are ephemeral and in-memory** — a restart clears them; nothing about them is persisted.
- **Real RTSP decode needs PyAV** (`pip install av`, a default dependency). Without it stream admission → `503`.
- **`synthetic` detections are fixtures**, not real inference. Production detection requires an engine plugin adapter.
- **MJPEG viewer count is not capped** (`max_viewers` is reserved), and SSE heartbeats are comment lines, not typed events.
- The old contract's sources/pipelines/sessions/monitors/media/jobs/recordings/zones/rules/personas/event-bus surface was **retired at v1.7.1** — the ledger in `specs/OPAL_LOOK_V1_7_LEDGER.md` records the migration.

---

## Tests, contract, and contributing

~~~bash
.venv/Scripts/pytest                                   # full suite
python -m opal_look.contract_audit --strict            # conformance gate (47 ops)
~~~

The audit diffs implemented routes against the pinned `openapi/opal_look_v1.7.1.yaml` and reports missing ops, legacy-only routes, and contract-structure problems. The contract files are authoritative — **don't edit them in-tree**; amendments go upstream first (`specs/` holds the ledger and drafts). `AGENTS.md` documents architecture, conventions, and per-area conformance status for contributors.

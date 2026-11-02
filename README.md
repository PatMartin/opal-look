# OPAL Look

**Vision for the OPAL ecosystem.** OPAL Look provides a REST-first service for image analysis, media, camera/source configuration, analysis sessions, and results. It includes a Typer command-line client and a browser-based interface that both communicate through the REST API.

> **Current release:** Python package `0.1.0`, implementing the `opal_look_v1.4.0.yaml` contract. Some camera and video capabilities remain adapter-dependent; see [Current limitations](#current-limitations).

## QUICKSTART

### 1. Install

You need **Python 3.12+** and Git. The commands below use Linux/macOS; on Windows, activate the environment using `.venv\Scripts\activate` instead.

```bash
git clone https://github.com/PatMartin/opal-look.git
cd opal-look
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### 2. Start OPAL Look

```bash
opal-look
```

By default, the API listens at **http://127.0.0.1:8000**. Open:

- **Web app:** http://127.0.0.1:8000/app/
- **API documentation:** http://127.0.0.1:8000/docs
- **Health endpoint:** http://127.0.0.1:8000/api/v1/health/

Keep the server running. Open a second terminal, activate the same virtual environment, and try:

```bash
opal-look-cli health
opal-look-cli engines list
opal-look-cli models list
opal-look-cli settings show
```

### 3. Try image analysis without a camera

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
| --- | --- |
| REST API | FastAPI service aligned to the bundled OpenAPI contract |
| Browser UI | SPA at `/app/` |
| CLI | Typer client using HTTP requests to the REST service |
| Engines and models | List, configure, and validate vision adapters and models |
| Sources and profiles | Manage input sources and reusable analysis profiles |
| Media | Upload, inspect, download, and delete images |
| Analysis | Run supported analysis tasks and retrieve stored results |
| Sessions | Create, inspect, stop, and delete analysis sessions |
| Snapshots and streams | Capture results/snapshots and use supported stream endpoints |
| Settings | Read and change individual settings with revision checks |
| Backup | Export, import, validate, create, and restore backups |
| Events | Optional ZeroMQ event publication, disabled by default |

## CLI examples

The CLI uses **`opal-look-cli`**; **`opal-look`** starts the API server. Use `--help` at any level to explore available commands.

```bash
# General
opal-look-cli --help
opal-look-cli info
opal-look-cli health

# Inspect engines, models, cameras, and sources
opal-look-cli engines list
opal-look-cli models show synthetic-vision
opal-look-cli devices cameras
opal-look-cli sources list

# Inspect settings and uploaded media
opal-look-cli settings show max_upload_bytes
opal-look-cli media list
opal-look-cli results list

# Sessions and backups
opal-look-cli sessions list
opal-look-cli backup validate
opal-look-cli backup create

# Connect to a server at a different address
opal-look-cli --url http://127.0.0.1:9000 health

# Machine-readable output
opal-look-cli --json models list
```

For configuration collections, common verbs include `list`, `show`, `add`, `update`, `remove`, and `validate`. Additional operations include `analyze run`, `media upload`, `profiles activate`, and `sessions stop`. Use `opal-look-cli <group> --help` for exact arguments and options.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `OPAL_LOOK_HOST` | `127.0.0.1` | API bind address |
| `OPAL_LOOK_PORT` | `8000` | API port |
| `OPAL_LOOK_DATA_DIR` | `./data` | Persistent application data directory |
| `OPAL_LOOK_EVENT_TRANSPORT` | Unset | Provisioned ZeroMQ event transport configuration |
| `OPAL_LOOK_CRED_<REF>` | Unset | `user:pass` credentials for a source `credential_ref` (e.g. `OPAL_LOOK_CRED_DRIVEWAY`) |

For example:

```bash
OPAL_LOOK_PORT=9000 OPAL_LOOK_DATA_DIR=./look-data opal-look
```

Event publication is **off by default**. Enabling it requires provisioned event transport configuration. Configuration writes use revision / `If-Match` checks to avoid accidental overwrites; the CLI handles these for its supported mutation commands.

## Architecture and API contract

- **Contract:** [`opal_look_v1.4.0.yaml`](opal_look_v1.4.0.yaml) is the authoritative OpenAPI specification.
- **Service:** `src/opal_look/` contains the FastAPI application, repositories, adapters, and workflows.
- **CLI:** `src/opal_look_cli/` implements the REST-only Typer client.
- **Web app:** `src/opal_look/static/` contains the browser client.
- **Tests:** `tests/` contains the pytest suite.
- **Contributor conventions:** [`AGENTS.md`](AGENTS.md) describes implementation patterns, invariants, and coverage.

The implementation uses repository abstractions for persistence, an engine adapter/registry model, dependency injection, correlation middleware, and consistent API error envelopes.

## Current limitations

- The built-in synthetic engine demonstrates flows but does not perform real trained-model inference. Additional engine adapters are needed for real model inference.
- RTSP sources are supported through the PyAV capture adapter (with live sessions, reconnect backoff, and single-frame analyze). Camera devices, HTTP/MJPEG feeds, and host_video decoding still require additional source adapters; configuring such a source does not by itself guarantee a usable feed.
- Some SSE replay-window edge cases and operational counters remain deferred.

Refer to [`AGENTS.md`](AGENTS.md) for the latest implementation-coverage notes.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest

# Alternate way to start the service
uvicorn opal_look.app:create_app --factory --host 127.0.0.1 --port 8000
```

Make changes in small, testable steps and keep REST behavior aligned with the checked-in OpenAPI contract.

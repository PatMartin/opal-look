# OPAL Look Cookbook

Practical, copy/pasteable workflows for OPAL Look **v0.1.0**.

Every fenced shell block has GitHub's built-in **Copy** button. Run the
commands from a shell with the OPAL Look environment installed. `opal look …`
and `opal-look …` are the same REST client; the recipes use `look` as an
alias.

## Before You Start

Start the service in one terminal:

```bash
opal serve            # or: python -m opal_look
```

In another terminal, set the alias (and `--url` if not on the default):

```bash
export LOOK=http://127.0.0.1:8002
alias look='opal-look --url "$LOOK"'

look info ready
look engine list
```

The bundled `synthetic` engine produces deterministic, detection-shaped test
output — useful for exercising workflows, **not** for real-world decisions.
Real RTSP decode requires PyAV (`pip install av`); without it, stream
admission answers `503`.

If the server was started with `OPAL_LOOK_TOKEN`, the CLI sends it
automatically when the variable is set in your shell too.

## Things OPAL Look Can Do On Its Own

### 1. Check the service end to end

```bash
look info health       # aggregated readiness incl. database + engines
```

### 2. Inventory the inference engine catalog

Engines are adapters: `synthetic` is built in, remote adapters register
from env (`OPAL_LOOK_ENGINE_YOLO_BASE_URL` → `yolo`; see recipe 11), and
third-party plugins register via the `opal_look.engines` entry-point
group.

```bash
look engine list
look engine show synthetic
look engine capabilities synthetic
look engine discover   # re-scan entry points -> {engines, errors}
```

Each row shows `enabled` (your flag) and `state` (live probe) — an
enabled-but-`unavailable` engine fails inference calls with `503`; the
`engine show` `message` says why.

### 3. Load a model and run detection on a photo

Models are engine-federated: always `load` before `predict`.

```bash
look model list
look model load synthetic-det --engine synthetic
look predict image --engine synthetic --model synthetic-det --source ./sample.jpg
look predict image --engine synthetic --model synthetic-det \
  --source ./sample.jpg --confidence 0.5
```

### 4. Load a model on a specific device

```bash
look hardware list --engine synthetic
look model show synthetic-det --engine synthetic
```

### 5. Start a plain video stream

Engine-free: no `engine_id` means video mode. Admission returns `202` with a
`Location` header; one decode feeds every consumer.

```bash
look stream start rtsp://camera.example.invalid:554/stream1
look stream list
```

### 6. Name the stream so the URLs are yours

`--name` pins the stream id used in every path and status record. A live
name conflict → `409`; a stopped/failed name is free to reuse.

```bash
look stream start rtsp://camera.example.invalid:554/stream1 --name front
look stream show front
curl -s "$LOOK/api/v1/stream/front"            # same record over REST
```

### 7. Watch and record the live feed end to end

Full flow: start a named stream, verify it, watch it live, record it.

```bash
# 1. Start the stream under a name you choose:
look stream start rtsp://192.168.1.220:554/stream1 --name front-hi
look stream list                # -> stream_id "front-hi", status running

# 2. Watch it live — MJPEG plays in any multipart-aware viewer,
#    no second camera connection:
ffplay -fflags nobuffer http://127.0.0.1:8002/api/v1/stream/front-hi/video
vlc    http://127.0.0.1:8002/api/v1/stream/front-hi/video
#    (add `-f mpjpeg` before the URL if ffplay's probe stalls)

# 3. Record it — either bounded via the CLI:
look stream watch-video front-hi --out front-hi.mjpeg --max-bytes 50000000

#    or unbounded with ffmpeg itself (Ctrl-C to stop):
ffmpeg -fflags nobuffer -i http://127.0.0.1:8002/api/v1/stream/front-hi/video -c:v copy front-hi.mjpeg

# 4. Play the recording back / remux to mp4:
ffplay -f mpjpeg front-hi.mjpeg
ffmpeg -f mpjpeg -i front-hi.mjpeg -c:v libx264 front-hi.mp4

# 5. Stop when done:
look stream stop front-hi
```

The SPA at `http://127.0.0.1:8002/app/` shows the same feed in-browser.
When `OPAL_LOOK_TOKEN` is set, pass
`-headers "Authorization: Bearer <token>\r\n"` to ffplay/ffmpeg.

### 8. Grab a single frame

```bash
look stream snapshot front --out front-snap.jpg
curl -so snap.jpg "$LOOK/api/v1/stream/front/snapshot"
```

### 9. Follow stream events over SSE

`frame`, `detection` (inference streams), `status`, and a `terminal` event;
heartbeats arrive as comments. `Last-Event-ID` replays the bounded buffer.

```bash
look stream watch front                       # Ctrl-C to detach
curl -N "$LOOK/api/v1/stream/front/events"
curl -N -H 'Last-Event-ID: 42' "$LOOK/api/v1/stream/front/events"
```

### 10. Read live performance metrics

```bash
look stream metrics front
# uptime, input/output fps, queue depth, dropped frames, inference latency
```

### 11. Wire a real detector — the remote YOLO engine

`synthetic` proves the workflow; `yolo` gives real detections. It runs as
a separate service ([opal-look-yolo](https://github.com/PatMartin/opal-look-yolo),
typically on `:8086` — see [YOLO_INSTALL.md](YOLO_INSTALL.md)); look
proxies to it over HTTP. Wiring is one `.env` line + restart:

```bash
# .env
OPAL_LOOK_ENGINE_YOLO_BASE_URL=http://127.0.0.1:8086

look service stop && look service start

look engine list                       # yolo: enabled, state ready
look model list --engine yolo          # real models from the service
look model load yolo26n --engine yolo  # smallest/fastest for CPU
```

Predictions are a remote round-trip per frame — measured ~250 ms on
`yolo26n`/CPU, so inference streams run at single-digit fps (expected;
`stream metrics` shows `inference_latency_ms`). What the model can
identify: [yolo26n_classes.md](yolo26n_classes.md).

### 12. Run an inference stream with annotated overlays

Requires an enabled+available engine and a loaded model; `annotate` draws
boxes from each frame's detections.

```bash
# quick path — bundled test engine:
look model load synthetic-det --engine synthetic
look stream start rtsp://camera.example.invalid:554/stream1 \
  --name front-ai --engine synthetic --model synthetic-det --annotate

# real path — remote yolo (recipe 11), credentialed camera (recipe 20):
look model load yolo26n --engine yolo
look stream start rtsp://camera.example.invalid:554/stream1 \
  --name front-ai --credential front \
  --engine yolo --model yolo26n --annotate \
  --options '{"classes": [0]}'     # persons only

look stream watch front-ai          # `detection` events now flow
vlc "http://127.0.0.1:8002/api/v1/stream/front-ai/video?annotated=true"
look stream snapshot front-ai --annotated --out front-boxes.jpg
```

### 13. Retry-safe admission with Idempotency-Key

Same key + same body replays the original admission instead of starting a
second stream; a different body under a reused key → `409`.

```bash
curl -si -X POST "$LOOK/api/v1/stream/" \
  -H 'Idempotency-Key: admit-front-001' \
  -H 'Content-Type: application/json' \
  -d '{"source":"rtsp://camera.example.invalid:554/stream1","name":"front"}'
```

### 14. Stop a stream and free its name

```bash
look stream stop front
look stream stop front      # -> 409, already stopped
look stream start rtsp://camera.example.invalid:554/stream1 --name front
```

### 15. Tune global settings

Mutations send `If-Match` automatically; a stale revision → `412`.

```bash
look config setting list
look config setting show max_concurrent_streams
look config setting set max_concurrent_streams 8
look config setting update --body '{"sse_buffer_events":512}'
```

Alternatively, pin settings declaratively in `.env` — any
`OPAL_LOOK_<SETTING_KEY>` (e.g. `OPAL_LOOK_MAX_CONCURRENT_STREAMS=8`) is
seeded as an override at startup and is authoritative over API-set values.
`.env` is loaded per process at every boot, so it also survives managed
restarts; shell-exported vars do not propagate through a REST `service
start` (the new process inherits the old server's environment).

### 16. Record deployment posture with profiles

Profiles are portable namespaced documents (kernel `OpalProfile`): a
`shared` compartment plus per-module `modules` compartments preserved
verbatim; exactly one is locally active at a time. Look records which is
active (`info health` reports `active_profile_id`); foreign compartments
belong to their owning modules and are read-only here.

```bash
look profile add --body '{"name":"night-watch","stream_defaults":{"buffer_policy":"drop-newest"}}'
look profile list
look profile activate PROFILE_ID
look profile show PROFILE_ID
```

### 17. Save, validate, and restore configuration

Portable OpalConfigSnapshot documents: `config save --out` captures the
live config to a file, `config save` replaces the server's managed
recovery snapshot.

```bash
look config save --out look-config.json
look config validate --in look-config.json
look config load --in look-config.json
```

### 18. Managed snapshot

The single managed snapshot lives in the service store.

```bash
look config save        # write/replace the managed snapshot
look config load        # atomically restore it (If-Match required)
```

### 19. Operate the service lifecycle

REST-first, with a pidfile fallback when the API is unreachable.

```bash
look service log --lines 20
look service stop            # managed process exits after responding
look service start           # respawns (restarts if one is running)
```

### 20. Provision RTSP credentials without leaking them

Credentials live in `OPAL_LOOK_CRED_<REF>` env vars holding `user:pass`.
Name one per stream with `credential_ref` — the credential is injected
into the locator only at connect time and never stored, logged, or echoed
(`source_redacted` strips userinfo).

```bash
# .env (preferred — picked up at service startup)
OPAL_LOOK_CRED_DRIVEWAY=opallook:secret

look stream start rtsp://camera.example.invalid/stream \
    --name driveway --credential driveway
```

An unprovisioned or malformed (`user:pass` required) ref is rejected at
admission with 422 — the error names the expected env var. You can also
embed `user:pass@` in the source URI directly (still redacted in API
output, but it lands in your shell history).

### 21. Gate conformance before shipping

```bash
opal-look-audit --strict     # or: python -m opal_look.contract_audit --strict
# RESULT: CONFORMANT when all 45 contract ops are implemented
```

## Cross-Module OPAL Workflows

The v0.1.0 contract is deliberately small; sibling modules integrate over
the stream/predict/config surface:

- **opal-look-yolo** is the working example — a remote engine service
  wired via `OPAL_LOOK_ENGINE_YOLO_BASE_URL` (recipe 11); full guide in
  [YOLO_INSTALL.md](YOLO_INSTALL.md).
- **OPAL Event** can fan `detection` SSE events from `…/events` out to
  automations — subscribe with `curl -N` or a small SSE client and publish
  onward.
- **OPAL Think** can poll `predict` on captured snapshots, or consume stream
  events for reasoning.
- **OPAL Listen/Talk** can drive `stream start --name` + `snapshot` for
  voice-requested live views; Look supplies the JPEG, Talk describes it.
- **Config portability:** `config save --out`/`config load --in` moves a Look setup
  between sites; `config validate` checks a snapshot before applying it.

The sibling modules have independent contracts — substitute their deployed
endpoints for the placeholders above. Do not wire synthetic detections to
physical-world actions.

## Operational Notes

- Put `--url "$LOOK"` before the command group (see the `look` alias).
- `--json` gives machine-readable output for `jq` pipelines.
- `stream watch`/SSE runs until `Ctrl-C`; viewers never stop the stream.
- Streams are ephemeral: a service restart clears them. `stream start`
  again under the same `--name`.
- Secure every OPAL service independently in production, and require human
  authorization for actions with safety, privacy, or access-control impact.

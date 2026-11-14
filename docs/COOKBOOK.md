# OPAL Look Cookbook

Practical, copy/pasteable workflows for OPAL Look **v1.7.1**.

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
export LOOK=http://127.0.0.1:8000
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
look info ping
look info version
```

### 2. Inventory the inference engine catalog

Engines are discovered adapters; an empty catalog is healthy (video streams
don't need one).

```bash
look engine list
look engine show synthetic
look engine capabilities synthetic
look engine discover   # re-scan entry points -> {engines, errors}
```

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

### 7. Watch the live view

MJPEG plays in any multipart-aware viewer — no second camera connection.

```bash
# Save a bounded capture to disk:
look stream watch-video front --out front.mjpeg --max-bytes 5000000

# Or point a player at the URL directly:
vlc http://127.0.0.1:8000/api/v1/stream/front/video
ffplay -f mpjpeg http://127.0.0.1:8000/api/v1/stream/front/video
```

The SPA at `http://127.0.0.1:8000/app/` shows the same feed in-browser.

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

### 11. Run an inference stream with annotated overlays

Requires a loaded model; `annotate` adds the box-drawing overlay on top of
detections.

```bash
look model load synthetic-det --engine synthetic
look stream start rtsp://camera.example.invalid:554/stream1 \
  --name front-ai --engine synthetic --model synthetic-det --annotate

look stream watch front-ai          # `detection` events now flow
vlc "http://127.0.0.1:8000/api/v1/stream/front-ai/video?annotated=true"
look stream snapshot front-ai --annotated --out front-boxes.jpg
```

### 12. Retry-safe admission with Idempotency-Key

Same key + same body replays the original admission instead of starting a
second stream; a different body under a reused key → `409`.

```bash
curl -si -X POST "$LOOK/api/v1/stream/" \
  -H 'Idempotency-Key: admit-front-001' \
  -H 'Content-Type: application/json' \
  -d '{"source":"rtsp://camera.example.invalid:554/stream1","name":"front"}'
```

### 13. Stop a stream and free its name

```bash
look stream stop front
look stream stop front      # -> 409, already stopped
look stream start rtsp://camera.example.invalid:554/stream1 --name front
```

### 14. Tune global settings

Mutations send `If-Match` automatically; a stale revision → `412`.

```bash
look config setting list
look config setting show max_concurrent_streams
look config setting set max_concurrent_streams 8
look config setting update --body '{"sse_buffer_events":512}'
```

### 15. Record deployment posture with profiles

Profiles are named bundles — extra fields are stored verbatim (kernel
`OpalProfile`); exactly one is active at a time. Look records which is
active (`info health` reports `active_profile_id`); what the fields mean
is up to your clients.

```bash
look config profile add --body '{"name":"night-watch","stream_defaults":{"buffer_policy":"drop-newest"}}'
look config profile list
look config profile activate PROFILE_ID
look config profile show PROFILE_ID
```

### 16. Export, validate, and restore configuration

```bash
look backup export > look-config.json
look backup validate --file look-config.json
look backup import --file look-config.json
```

### 17. Managed backup archives

Server-side archives under `<data_dir>/backups/`.

```bash
look backup create
look backup list
look backup download opal-look-YYYYMMDDTHHMMSSZ.json --out copy.json
look backup restore opal-look-YYYYMMDDTHHMMSSZ.json
look backup remove opal-look-YYYYMMDDTHHMMSSZ.json
```

### 18. Operate the service lifecycle

REST-first, with a pidfile fallback when the API is unreachable.

```bash
look service log --lines 20
look service stop            # managed process exits after responding
look service start           # respawns (restarts if one is running)
```

### 19. Provision RTSP credentials without leaking them

Credentials live in `OPAL_LOOK_CRED_<REF>` env vars, injected only at
connect time — never stored, logged, or echoed in `source_redacted`.

```bash
export OPAL_LOOK_CRED_DRIVEWAY='user:password'
# then use the locator normally; the URI itself stays redacted:
look stream start rtsp://camera.example.invalid/stream --name driveway
```

### 20. Gate conformance before shipping

```bash
opal-look-audit --strict     # or: python -m opal_look.contract_audit --strict
# RESULT: CONFORMANT when all 47 contract ops are implemented
```

## Cross-Module OPAL Workflows

The v1.7.1 contract is deliberately small; sibling modules integrate over
the stream/predict/backup surface:

- **OPAL Event** can fan `detection` SSE events from `…/events` out to
  automations — subscribe with `curl -N` or a small SSE client and publish
  onward.
- **OPAL Think** can poll `predict` on captured snapshots, or consume stream
  events for reasoning.
- **OPAL Listen/Talk** can drive `stream start --name` + `snapshot` for
  voice-requested live views; Look supplies the JPEG, Talk describes it.
- **Config portability:** `backup export`/`import` moves a Look setup
  between sites; `validate` checks a bundle before applying it.

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

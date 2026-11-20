# Stream identity, teardown, and the Event bridge

## Three identities you must not conflate

| Identifier | Who chooses it | Lifetime | Used for |
|---|---|---|---|
| **Camera/stream name** (`name`) | Client, at admission | A label — unique only among *non-terminal* streams | Human-friendly lookup alias: `GET /api/v1/stream/{name}` resolves while the name is held. Reusable after the holder reaches a terminal state. |
| **Run ID** (`stream_id`, `strm_…`) | Server-generated per admission | Immutable for the life of one run; never reused | Canonical resource identity: `Location`, status/stop/video/events/snapshot URLs, receipts. A name reuse creates a *new* run id — nothing about the old run survives. |
| **Replay key** (`Idempotency-Key`) | Client, per admission request | 24 h TTL (durable) | Retry dedup: the same key + same body returns the recorded run's receipt (the exact `stream_id`, even across restarts); same key + different body → 409. The key is bound to the *run id*, not the name, so a retry after name reuse still returns the original run's receipt. |

A fourth id appears on the wire: the **SSE event sequence** (`id:` on each
event). It is per-run and monotonically increasing — use it with
`Last-Event-ID` to resume after a disconnect, and as the dedup component
when bridging detections.

Retry semantics summary: retry before expiry → identical 202 receipt;
retry after stop → the receipt still points at the (terminal) run;
retry after expiry → fresh admission; concurrent same-key requests are
admitted once under the admission lock.

## Teardown and fan-out semantics

- `POST .../stop` → 202-style `stopping`/`stopped`. Terminal status is
  published **only after** the decode thread exits and the capture
  stream is closed — `stopped` means resources are released. If the
  decoder outlives `teardown_grace_seconds`, the stream reports
  `failed` (`teardown_timeout`) rather than a false `stopped`.
- Subscribers (SSE + MJPEG) share one decode pump. A subscriber whose
  queue fills is evicted with a final `dropped` event and its response
  ends — it never stalls the stream.
- Viewer occupancy is bounded by `max_viewers` across both surfaces
  (429 when full); `snapshot` is uncounted.
- JPEG output is encoded once per frame+variant and shared by equal
  requests; entries expire after `frame_cache_seconds`.

## Source policy

`POST /api/v1/predict/` and `POST /api/v1/stream/` validate the source
**before** any I/O. Local image paths must resolve under
`source_local_roots` (deny-by-default). Remote destinations must match
`source_allowed_hosts` (host, `host:port`, IP, or CIDR) or, when
`source_allow_private` is set, resolve to private/loopback space.
HTTP(S) redirects are re-checked hop by hop, bodies are bounded while
bytes arrive (`max_upload_bytes`), and dimensions are checked before
full decode. Denials are sanitized 422s — no paths, hosts, or
credentials leak into responses or logs.

## Detection → Event bridge (opt-in)

`opal-look stream bridge <stream> --event-url <base>` consumes the
stream's detection SSE and publishes `EventInput` envelopes to an OPAL
Event service (`POST /api/v1/events/`). Nothing bridges unless the verb
runs.

- **Envelope**: `{id, topic: <topic_prefix>.<camera>, source,
  timestamp, data:{camera, stream_id, frame, sse_seq, detections,
  top_class, top_confidence, count}}`.
- **Filters**: `--min-confidence`, `--classes`, `--cooldown` (per
  camera; patterns are fnmatch globs on the stream name).
- **Dedup**: `id` is `uuid5(stream_id, sse_seq)` — deterministic across
  replays. The bridge also suppresses replayed `(run, seq)` keys after
  `Last-Event-ID` reconnects, so a replay can never double-publish.
- **Retries**: publish retries bounded (`publish_attempts`, default 4;
  5xx/transport back off, 4xx fails fast); SSE reconnects use capped
  exponential backoff, unlimited unless `--max-reconnects` is given.

### Tested commands (synthetic fixture)

```
# mock SSE + mock Event service — tests/test_event_bridge.py
.venv/Scripts/pytest tests/test_event_bridge.py
```

### Tested commands (live, requires LAN camera + .env)

```
.venv/Scripts/python scripts/live_bridge.py
# admitted inference stream on rtsp://192.168.1.220:554/stream1
# (credential_ref FRONT), synthetic engine; bridge published 5
# normalized Events (topic look.detection.front) to a mock Event
# service; clean exit on stream terminal.
```

CLI form:

```
opal-look stream bridge front --event-url http://127.0.0.1:PORT \
    --min-confidence 0.6 --classes person,car --cooldown 10
# or OPAL_EVENT_URL / OPAL_EVENT_TOKEN env vars
```

## YOLO path (remote adapter)

The adapter registers when `OPAL_LOOK_ENGINE_YOLO_BASE_URL` is set and
proxies the standalone `opal-look-yolo` service
(`openapi/engines/opal_look_yolo_v0.1.0.yaml`).

```
# simulated adapter contract — tests/test_engines_yolo.py,
# tests/test_engine_contract.py
.venv/Scripts/pytest tests/test_engines_yolo.py tests/test_engine_contract.py

# live service (when running at OPAL_LOOK_ENGINE_YOLO_BASE_URL):
opal-look engine list                 # yolo shows available
opal-look model load yolov8n --engine yolo
opal-look stream start rtsp://cam --engine yolo --model yolov8n
```

The conformance suite (`tests/test_engine_contract.py`) is the gate any
future engine adapter must pass: discovery surface, model lifecycle,
readiness probe, normalized detections, and error translation.

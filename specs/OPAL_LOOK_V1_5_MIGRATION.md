# OPAL LOOK 1.5.0 — Simplified Contract Migration Guide

**Status:** Draft for architectural review. **Source of truth for comparison:** [`PatMartin/opal-api/openapi/opal_look.yaml`](https://github.com/PatMartin/opal-api/blob/main/openapi/opal_look.yaml), version 1.4.0. This draft is a **breaking v1.5.0 revision** of the v1 API. It is **not wire-compatible with v1.4.0**, even though the path prefix remains `/api/v1`; the opal-look implementation does not yet support it.

## Summary

| Measure | Existing opal-api | This draft |
|---|---:|---:|
| OpenAPI version | 3.1.0 | 3.1.0 |
| API contract version | 1.4.0 | 1.5.0 (draft) |
| REST path prefix | `/api/v1` | `/api/v1` |
| Paths | 58 | 42 |
| HTTP operations | 90 | 62 |
| Public configuration resource types | Sources, engines, models, pipelines, profiles, zones, rules, monitors | Sources, engines, models, pipelines, monitors |

This removes **28 HTTP operations (~31%)**, while retaining the advanced pipeline DAG, model/engine interchangeability, finite jobs, typed observations, source frame access, viewer streams, recordings, diagnostics, and events.

## Seven important changes

1. **No public sessions.** A viewing connection is ephemeral. The server manages decoder, inference, viewer and reconnection lifetimes. For durable background observation, create a monitor; for bounded work, submit a job.
2. **No separate profiles.** Pipelines own inference options and retention defaults. A pipeline can be a simple `model_id` + `task`, or an advanced ordered DAG of stages.
3. **Zones belong to sources.** `SourceCreate.zones` and `SourcePatch.zones` contain named polygons/lines. Updates replace the zone array atomically and require `If-Match`.
4. **Rules become monitor conditions.** A monitor binds a source and pipeline and contains conditions such as `enters_zone`, `motion_detected`, `dwell_time`, and `line_crosses`. It only detects; OPAL-EVENT performs actions.
5. **Captures and artifacts become media.** Uploads, captures, clips, recordings, and generated output all use `/media`, with explicit `kind`, `origin`, ownership, TTL, and conflict-aware deletion.
6. **Direct viewer.** `/sources/{source_id}/stream` provides raw MJPEG without a pipeline; specifying a pipeline enables connection-scoped inference with overlays on by default. The caller never starts a session.
7. **Version 1.5.0 is intentionally breaking.** It retains `/api/v1`, but changes paths and payloads. This is a deliberate exception to semantic versioning. Do not deploy it over v1.4.0 without migrating all consumers; use a separate instance, port, or deployment during the transition.

## REST examples

These examples describe the new contract. They **will not work** against a deployment that only implements v1.4.0.

Set `BASE=http://127.0.0.1:8080/api/v1` and configure `OPAL_TOKEN` for authenticated deployments. For portable configuration writes, `If-Match: *` is allowed by this contract; production tooling should normally read and send a concrete strong ETag to avoid accidentally overwriting concurrent changes.

### Register a camera and source-local zone

```bash
curl -X POST "$BASE/sources/" \
  -H "Authorization: Bearer $OPAL_TOKEN" -H 'If-Match: *' \
  -H 'Content-Type: application/json' \
  -d '{
    "id":"driveway", "kind":"rtsp", "name":"Driveway",
    "locator":"rtsp://192.168.1.50/stream1",
    "zones":[{"id":"entry","name":"Driveway entry","kind":"polygon",
      "points":[{"x":0.1,"y":0.2},{"x":0.9,"y":0.2},{"x":0.9,"y":0.9}]}]
  }'
```

### Register a simple reusable detection pipeline

Assumes the `yolo-small` model has already been registered with an installed inference engine.

```bash
curl -X POST "$BASE/pipelines/" \
  -H "Authorization: Bearer $OPAL_TOKEN" -H 'If-Match: *' \
  -H 'Content-Type: application/json' \
  -d '{
    "id":"people", "name":"People detector",
    "model_id":"yolo-small", "task":"detection",
    "options":{"confidence_threshold":0.6,"classes":["person"]},
    "retention":{"persist_observations":false}
  }'
```

Advanced pipelines still support ordered `stages`, including filters, motion gating, trackers and annotations. `stages` cannot be combined with the `model_id`/`task` shorthand in a single request.

### Watch and analyze without session management

```bash
# MJPEG, raw frames, no inference:
curl -N "$BASE/sources/driveway/stream" -H "Authorization: Bearer $OPAL_TOKEN"

# MJPEG with object detection and visual overlays:
curl -N "$BASE/sources/driveway/stream?pipeline_id=people" \
  -H "Authorization: Bearer $OPAL_TOKEN"

# One-frame detection, synchronous JSON:
curl -X POST "$BASE/analyze/" \
  -H "Authorization: Bearer $OPAL_TOKEN" -H 'Content-Type: application/json' \
  -d '{"source":{"source_id":"driveway"},"pipeline_id":"people"}'
```

For a browser app requiring bearer auth, use the service's authenticated SPA or approved same-origin proxy. **Do not put bearer credentials in stream URLs.** A viewer disconnect does **not** stop a monitor or recording.

### Monitor continuously with inline conditions

```bash
curl -X POST "$BASE/monitors/" \
  -H "Authorization: Bearer $OPAL_TOKEN" -H 'If-Match: *' \
  -H 'Content-Type: application/json' \
  -d '{
    "id":"driveway-watch", "name":"Driveway watch",
    "source_id":"driveway", "pipeline_id":"people",
    "enabled":true,
    "conditions":[{"id":"entry-person","event":"enters_zone",
      "zone_id":"entry","classes":["person"],"cooldown_ms":30000}],
    "publish_events":true
  }'
```

To actually emit to OPAL-EVENT, the global `events_enabled` setting, an allowlist, and transport must also be configured. This contract **does not guarantee event delivery**. Users can subscribe to the running monitor's SSE output at `/monitors/driveway-watch/observations/stream` with bounded replay via `Last-Event-ID`.

### Retain an exact snapshot

```bash
curl -X POST "$BASE/sources/driveway/capture" \
  -H "Authorization: Bearer $OPAL_TOKEN" -H 'Content-Type: application/json' \
  -d '{"pipeline_id":"people","annotated":true,"ttl_seconds":3600}'
```

The response is a `Media` object. Retrieve the snapshot via `/media/{media_id}/content`; the server returns the actual image MIME type. For unretained current-frame access, use `GET /sources/{source_id}/frame` instead.

## v1.4.0 → v1.5.0 migration mapping

| v1.4.0 public concept/path | v1.5.0 replacement | Important behavior change |
|---|---|---|
| `/profiles/` and global activate | `Pipeline.options`, `Pipeline.retention`, `Settings.default_pipeline_id` | No hidden globally active profile; callers may choose a pipeline explicitly |
| `/sessions/` | Ephemeral `/sources/{id}/stream` or `/sources/{id}/observations/stream`; durable `/monitors/` | No user-managed viewer sessions; direct SSE replay only on monitors |
| `/zones/` | `Source.zones` | Source-local ID; updates replace complete zones array |
| `/rules/` | `Monitor.conditions` | Conditions run only from observations; no arbitrary action execution |
| `/captures/` | `/media/` with `kind=snapshot` | One metadata/download/deletion interface |
| `/artifacts/` | `/media/` with `kind=derived_image`, `derived_video`, or `clip` | Output IDs become `media_id` |
| `/recordings/` | `/recordings/` + `media_id` on completion | Explicit, independent recording; recording output available in `/media` |
| `/jobs/` | `/jobs/` | Retained; finite processing output references media IDs |
| `/observations/` | `/observations/` | Retained; metadata immutable and opt-in persistence |
| `/configuration/export` | `/configuration/export` | Redacted source locators need rebinding at import |

## Compatibility and implementation cautions

- **Do not migrate blindly.** The active `opal-look` implementation has been developed against a different contract than the canonical `opal-api` file. This draft is a replacement target, not a statement of implemented endpoints.
- Keep **OpenAPI 3.1, OPAL error envelopes, correlation headers, one-setting-at-a-time updates, capability discovery, and strong config ETags** intact.
- Retain the full DAG as the advanced pipeline mode; don't remove tracking, segmentation, OCR, transforms, motion gates or typed observations to shorten the YAML.
- The server must enforce **resource quotas**, a cap on stream viewers/monitors/jobs, and no unbounded frame queues. Motion state after startup or disruption is **unknown**, never falsely classified as no motion.
- Annotated viewing, recordings, exports, persistence, and event publication are **separate opt-ins**. Viewing never implies saving or event emission.
- Source URLs and credentials must never appear unredacted in GET or portable exports. `ConfigurationImport.source_bindings` accepts new locators; absent bindings may be reused by source ID from the existing deployment or must fail explicitly.
- Browser authentication for MJPEG/SSE needs deliberate implementation: no authorization tokens in query strings.
- Model resources must be already provisioned. Engine-specific options are validated against advertised schemas; unsupported tasks or incompatible pipeline stages fail 422.
- Strong ETag (`If-Match`) protects portable configuration mutations. A missing header is 428 and a stale revision is 412, including nested source zone and monitor condition updates.
- Because both contracts use `/api/v1`, preserve the old deployment on a separate instance/port while migrating clients. Avoid routing old and new requests to the same prefix on one backend. Switch traffic only once CLI, SPA, third-party consumers and tests have been updated.

## Suggested build sequence (independently reviewable commits)

1. Ratify the v1.5.0 contract and schema-test it; keep a separate v1.4.0 deployment during migration.
2. Implement canonical source management, raw frame and source view first, including actual camera capture/decoding.
3. Implement basic pipeline shorthand plus advanced stage normalization and preflight validation.
4. Implement synchronous analyze (image, file/source frame), then connection-scoped annotated view and transient SSE.
5. Implement durable monitors with source-local zones, inline conditions, bounded monitor SSE replay and OPAL-EVENT publication.
6. Unify media storage and content retrieval, then adapt jobs, captures and recordings to `media_id`.
7. Implement configuration export/import binding safety, reconcile CLI/SPA with REST, and run end-to-end regression/evalsets before v1 deprecation.

## Validation performed on this draft

A Python structural/JSON Schema suite checked internal `$ref`s, schema validity under JSON Schema Draft 2020-12, unique operation IDs, CLI group/command pairs, path parameter wiring, standard responses/correlation headers, key workflow paths, and representative valid/invalid payloads. **It did not execute the service, perform full external OpenAPI tooling validation, or verify feature parity by running a migration.**

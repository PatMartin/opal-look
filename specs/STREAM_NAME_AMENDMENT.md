# Proposed upstream amendment: client-named streams

Target: `opal_look_v1.7.1.yaml` `StreamStartRequest` (next contract revision).

Add an optional `name` property. When supplied, it becomes the stream's
`stream_id` — the identifier used in `Location`, `StreamStatus`, and all
`/api/v1/stream/{stream_id}/*` paths. Absent, the server generates an
opaque `strm_*` id as today.

## Proposed schema delta

```yaml
StreamStartRequest:
  properties:
    name:
      type: string
      pattern: ^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$
      description: 'Client-chosen stream identifier, valid in video and
        inference modes. Must be unique among non-terminal streams:
        conflict with a starting/running/stopping stream => 409. A
        stopped/failed stream does not hold the name; re-admission
        replaces it. Omitted => server-generated id.'
```

`StreamStatus`, `StreamMetrics`, and the `StreamId` path parameter already
accept any `string minLength: 1`; no response-side changes needed.

## Semantics

- `name` is orthogonal to `engine_id` mode rules (allowed in video-only
  and inference admissions).
- 422 on pattern violation (path-unsafe characters rejected up front).
- 409 when a non-terminal stream already holds the id.
- Re-admission under a previously terminal id replaces the stale
  runtime record; the old stream's URLs then serve the new stream.
- `Idempotency-Key` admission unchanged: fingerprint covers `name`, and
  a fingerprint replay returns the admission recorded for the key.

## Implementation status

Implemented in this repo ahead of upstream acceptance (schemas
`StreamStartRequest.name`, `StreamRuntime(stream_id=...)`, admission
collision check under a lock, CLI `--name`, SPA field). Pinned yaml to be
refreshed when the upstream contract lands the field.

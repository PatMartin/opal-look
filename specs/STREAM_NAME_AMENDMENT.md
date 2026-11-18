# Proposed upstream amendment: client-named streams and run identity

Target: `opal_look_v1.7.1.yaml` `StreamStartRequest` and `StreamStatus`
(next contract revision).

Add an optional `name` property to `StreamStartRequest`, and a `name`
property to `StreamStatus`. `name` is a client-chosen label; it is NOT
the run identity. `stream_id` is always a server-generated opaque run id
(`strm_*`), immutable for the life of the run — every admission gets a
new id, including re-admissions under a previously used name.

## Proposed schema delta

```yaml
StreamStartRequest:
  properties:
    name:
      type: string
      pattern: ^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$
      description: 'Client-chosen stream label, valid in video and
        inference modes. Must be unique among non-terminal streams:
        conflict with a starting/running/stopping stream => 409. A
        stopped/failed stream does not hold the name; re-admission
        assigns it to the new run. Omitted => unnamed stream.'

StreamStatus:
  properties:
    name:
      type:
      - string
      - 'null'
      description: 'Client-chosen label from admission, or null. Unique
        among non-terminal streams only; do not use as a durable
        identifier — use stream_id.'
```

## Semantics

- `stream_id` is the run identity: `Location`,
  `/api/v1/stream/{stream_id}/*`, `events_url`, `video_url`, SSE
  `Last-Event-ID` scope, and idempotency receipt binding all use it.
- `name` additionally resolves as a lookup alias for convenience:
  `/api/v1/stream/{name}` (and subpaths) resolves the current
  non-terminal holder. Exact run-id matches win; a terminal stream
  releases the alias (its run remains addressable by run id).
- `name` is orthogonal to `engine_id` mode rules (allowed in video-only
  and inference admissions).
- 422 on pattern violation (path-unsafe characters rejected up front).
- 409 when a non-terminal stream already holds the name.
- `Idempotency-Key` admission binds the key to the run id
  (`session_id` column). A fingerprint replay returns the recorded run's
  receipt — even after the name moved to a replacement stream, a
  non-terminal stream is never returned for another run's key.
  After a restart (runtimes are ephemeral, the key row is durable) a
  fingerprint replay re-admits and rebinds the key to the new run; a
  mismatched fingerprint is 409 regardless. Keys expire after 24h;
  replay of an expired key is a fresh admission.

## Compatibility impact

- Responses gain a `name` field (`StreamStatus` is
  `additionalProperties: false` upstream — hence the amendment).
- Clients that treated `stream_id == name` must read `name` instead;
  `Location` and `stream_id` are the canonical run references.
- `/{name}` paths keep working via the alias while the name is held,
  so existing `stream/front-hi/video`-style URLs still resolve.

## Implementation status

Implemented in this repo ahead of upstream acceptance (schemas
`StreamStartRequest.name`, `StreamRuntime(name=..., stream_id=strm_*)`,
alias resolution in `_get_or_404`, atomic admission under
`_ADMISSION_LOCK`, run-id receipt binding in `idempotency_keys`).
Pinned yaml to be refreshed when the upstream contract lands the fields.

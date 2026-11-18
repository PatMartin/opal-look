# Proposed contract amendment: `credential_ref` on StreamStartRequest

Status: **DRAFT — for upstream review.** Implemented in this repo ahead of
upstream acceptance (same posture as `name`, specs/STREAM_NAME_AMENDMENT.md).
The pinned `openapi/opal_look_v1.7.1.yaml` is **not** edited locally; the
strict audit does not diff request schemas and remains CONFORMANT.

## Motivation

RTSP cameras commonly require HTTP digest/basic credentials. Look already
provisions them out of band — `OPAL_LOOK_CRED_<REF>` env vars holding
`user:pass`, injected only at connect time and never stored, logged, or
echoed (`source_redacted` strips userinfo). But `StreamStartRequest` had no
way to name *which* credential a source needs, so the injection code path
was unreachable: protected cameras failed admission with RTSP 401.

## Schema delta

`components/schemas/StreamStartRequest` — add one optional property:

```yaml
credential_ref:
  type: string
  pattern: '^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$'
  description: >-
    Names a provisioned credential: the value of environment variable
    OPAL_LOOK_CRED_<REF> (uppercased, non-alphanumeric -> '_'), holding
    'user:pass'. The credential is injected into the source URI only at
    connect time; it is never stored, logged, or echoed in responses.
    Optional; absent means the source carries no credential or embeds
    userinfo directly.
```

`additionalProperties: false` stays — this is an additive optional field,
backwards-compatible (existing admissions unchanged).

## Semantics

- **422** at admission when `credential_ref` is supplied but the env var is
  absent or not `user:pass`-shaped (fail fast rather than a failed stream
  — mirrors the missing-capture-adapter 503 gate).
- Credentials are URL-encoded into the locator's userinfo component at
  connect time only; the redacted source never contains them.
- Valid for both video and inference modes.
- `Idempotency-Key` fingerprint covers `credential_ref` like every other
  body field (replay with a different ref under the same key → 409).
- A source URI that already embeds userinfo plus a `credential_ref`:
  the provisioned credential **replaces** embedded userinfo (env is the
  authoritative credential store).

## Server-side precedent

`capture.credential_env_name()` / `resolve_credentials()` /
`credentialed_locator()` already implement the env-resolution and
URL-encoding rules above — this amendment exposes the existing mechanism
to admission requests. No new credential storage or logging surface.

## Test coverage (tests/test_streams.py)

- `test_credential_ref_injects_locator` — env-set ref → adapter receives
  `rtsp://user:pass@host/path`; status keeps `source_redacted` clean
- `test_credential_ref_unprovisioned_422` — missing env var → 422 naming
  the expected `OPAL_LOOK_CRED_<REF>`
- `test_credential_ref_malformed_env_422` — env var without ':' → 422
- `test_embedded_userinfo_redacted` — userinfo in `source` is stripped
  from `source_redacted`

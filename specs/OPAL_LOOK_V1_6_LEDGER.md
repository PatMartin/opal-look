# OPAL-LOOK v1.6.0 Migration Ledger

Living record of the v1.5.0 → v1.6.0 migration on `main`.
Update the coverage line after every step commit. The numbers below come from
the tools, not estimates — see "How to reproduce".

---

## Pinned inputs

- Contract: `openapi/opal_look_v1.6.0.yaml` SHA-256
  `7eecb525f6360f26e60b97dc8efb3def873ba3739b05a72b33a7680a1e8e604b`
  (`info.version: 1.6.0`). Service reports `contract_version: "1.6.0"`.
- Kernel: `openapi/shared/opal_kernel.yaml` (v1.6.0, was 1.2.0) SHA-256
  `0d41859bf0ef4a56017c4e5a1e92bac53215bd4ac62d8e49c86c947ea0827001`.
  Do not edit either; amendments go upstream first.
- Audit: `.venv/Scripts/python -m opal_look.contract_audit`
  (`--strict` gate, `--json` machine-readable). Audit resolves external
  `./shared/*` `$ref`s (pathItems + components).

## Contract delta (v1.5.0 → v1.6.0), verified by diff

1. **Plural → singular resource paths** on every resource family:
   `sources→source`, `engines→engine`, `models→model`, `pipelines→pipeline`,
   `profiles→profile`, `zones→zone`, `rules→rule`, `monitors→monitor`,
   `sessions→session`, `jobs→job`, `observations→observation`,
   `captures→capture`, `artifacts→artifact`, `settings→setting`,
   `recordings→recording` (incl. sub-paths `sessions/{id}/observations/` →
   `observation/`, `sources/{id}/captures/` → `capture/`). Unchanged:
   `media/`, `analyze/`, `capabilities/`, `metrics/`, `events/status`,
   `configuration/*`, `health/*`. OperationIds and `x-opal-cli`
   group/command unchanged on renamed paths; zero schema/param/response-code
   changes (deep diff: only a `Content-Type` param declaration on
   `POST /api/v1/media/`).
2. **New `persona` resource** — 6 ops: list (+`enabled` filter), create
   (If-Match, 201+Location, 409 on duplicate `persona_id`), get, patch,
   delete, validate. Schemas `PersonaCreate`/`PersonaUpdate`/`PersonaRead` +
   `PersonaId` param. Persona = named observer identity; optional OPAL Say
   `voice_id` binding (existence not validated locally). Decisions:
   personas ARE part of portable configuration export; `validate` checks
   exists + enabled + `voice_id` well-formed.
3. **New kernel `info` surface** — `GET /api/v1/info/` (`ServiceInfo`),
   `GET /api/v1/info/ping` (`LivenessRead`).
4. **Kernel 1.2.0 → 1.6.0** — opId renames on mounted pathItems
   (`opal_settings_get→opal_setting_list`, `opal_settings_patch→
   opal_setting_patch`, `opal_profiles_list→opal_profile_list`,
   `opal_profiles_create→opal_profile_create`, `opal_engines_list→
   opal_engine_list`); new `ServiceInfo`/`LivenessRead` schemas;
   `output_format` object→string in the TTS-flavoured kernel profile/engine
   schemas (no-op for Look: profiles are opaque data blobs).
5. **Schema cleanup** — `FrameDiagnostics`, `Id`, `MotionFilterParameters`,
   `SettingValue`, `Timestamp`, `ValidationIssue` removed from Look
   components; no property changes on shared schemas.

## Baseline (Step V01)

| Measure | Value |
|---|---|
| Contract inventory | 63 paths / 98 operations |
| Implemented routes | 92 ops |
| Covered | **15/98** |
| Missing | **83/98** — ~75 pure path renames + persona (6) + info (2) |
| Legacy-only `/api/v1` ops | 75 — all plural-path routes to hard-cut |
| Contract structural problems | 0 |

Three conformance tests in `tests/test_contract_audit.py` are
`xfail`-marked for the duration of the migration; un-xfail at certification.

## Step log

| Step | Commit | Covered /98 | Notes |
|---|---|---|---|
| V01 pin+audit retarget | e8b64a1 | 15 | contract swap committed; CONTRACT_VERSION 1.6.0; audit defaults to v1.6.0; conformance tests xfail'd; ledger opened |
| V02 singular paths | 076e3ee | 90 | scripted plural->singular rewrite across 21 routers / 37 test files / cli.py / app.js (745 + nested captures/,observations/ fixes); suite 489 green +3 xfail; 0 legacy-only |
| V03 info surface | a794b2a | 92 | /api/v1/info/ (ServiceInfo, same payload as /) + /api/v1/info/ping (LivenessRead); 2 health tests added |
| V04 personas | a647c60 | **98** | personas table+repo+router (CRUD+enabled filter+validate), portable-config personas section (export/validate/import), STRICT AUDIT CONFORMANT, xfail markers removed, suite 500 green |
| V05 CLI+SPA | 8e9a107 | 98 | persona group (list --enabled/add/show/update/remove/validate); bare `info` cmd -> info group (show/ping); SPA personas screen + ops info/ping |
| V06 certification | (this commit) | 98 | AGENTS.md/README/pyproject updated to v1.6.0; SPA/CLI docstrings + plural-path assertions refreshed; test-cli.sh `remove` verb fix |

**Result: strict audit CONFORMANT — 63 paths / 98 operations, 0 legacy-only,
0 contract problems.**

---

## How to reproduce

```sh
.venv/Scripts/python -m opal_look.contract_audit            # progress report
.venv/Scripts/python -m opal_look.contract_audit --strict   # pass/fail gate
.venv/Scripts/python -m opal_look.contract_audit --json     # machine-readable
.venv/Scripts/pytest                                        # full suite
```

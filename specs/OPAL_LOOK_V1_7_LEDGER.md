# OPAL-LOOK v1.7.1 Migration Ledger

Record of the v1.6.0 → v1.7.1 migration on `main` (7 steps, one commit each).

---

## Pinned inputs

- Contract: `openapi/opal_look_v1.7.1.yaml` (`info.version: 1.7.1`).
- Kernel: `openapi/shared/opal_kernel.yaml` (v1.7.1).
  Do not edit either; amendments go upstream first.
- Audit: `.venv/Scripts/python -m opal_look.contract_audit`
  (`--strict` gate, `--json` machine-readable).

## Contract delta (v1.6.0 → v1.7.1), verified by diff + live audit

1. **New `/api/v1/backup/*` family** (8 ops) — kernel `backup_*` pathItems:
   `export`/`validate`/`import` are the same pathItems v1.6.0 mounted at
   `/api/v1/configuration/*`; `list`/`create`/`download/{filename}`/
   `restore/{filename}`/`delete` are new server-managed archives.
   `backup import` accepts a null body → the `./config/` file set.
2. **New `/api/v1/service/*` family** (3 ops) — kernel `service_*`
   pathItems: start (doubles as restart), stop, log tail.
3. **Retired** — `/api/v1/configuration/{export,validate,import}` and
   `GET /api/v1/session/{session_id}/observation/`.
4. **x-opal-cli overhaul** — canonical `[parent] [group] <command>`:
   `config` parents model/pipeline/profile/zone/rule/monitor/setting/
   persona; `data` parents job/observation/media/capture/artifact/
   recording; singular group names; `info` absorbs health/live/ready/
   version/ping/capabilities/metrics/events; aliases `settings patch`,
   `settings reset`.
5. **Kernel 1.7.0 → 1.7.1** — persona schemas/params + `IdempotencyKey`
   moved to kernel (identical shapes); `x-opal-cli-format` descriptor
   spec; doc-only `profiles_vs_personas` + `x-opal-workflow-examples`.

## Design decisions

- **Backup archives** are single `opal-look-<UTCts>.json` files under
  `<data_dir>/backups/` holding the OpalConfigExport bundle — portable
  logical config only (redacted locators, never secrets/runtime state).
  `create` → 201 + `Location: /api/v1/backup/download/{filename}`;
  `restore` reuses the atomic import pipeline under mandatory If-Match
  and echoes `backup_filename` in the OpalImportResult. Filenames are
  validated against kernel BackupFilename rules plus a containment check.
- **Null-body import** reads `./config/*.json` when exactly one file is
  provisioned; 422 when the set is absent or ambiguous (Look is
  SQLite-based; no file set exists by default).
- **Service lifecycle is pidfile-managed**: the managed server is the
  process in `logs/opal_look.pid`, self-registered by `opal_look.main`.
  `start` spawns the detached replacement which waits on
  `OPAL_LOOK_WAIT_PID` for the old process to release the port; when the
  managed process is the serving one it exits ~1s after responding
  (abrupt on purpose — SSE/MJPEG clients must not stall the stop).
  `stop` is a no-op success when nothing is managed; `log` tails
  `logs/opal_look.log` (kernel bounds 1..1000, default 10) and 404s when
  absent. Fixes the stray `opal_listen.log` filename from v1.6.
- **CLI `service` verbs are REST-first** with a local pidfile/spawn
  fallback on connection failure — a dead server cannot answer REST.
- **CLI aliases** `settings patch`/`settings reset` are implemented as
  deprecated spellings dispatching to `config setting update|remove`.
- `config setting update` is now the contract whole-map PATCH
  (`/api/v1/setting/`); the old per-key PATCH spelling was never a real
  REST op. `source view` renamed to `source stream`; session
  `observations` verb dropped with the route.

## Step commits

| Step | Commit | Content |
|---|---|---|
| V01 | `4f158af` | pin v1.7.1 contract + audit baseline |
| V02 | `69bf94f` | remount configuration → /api/v1/backup/ export\|validate\|import |
| V03 | `b6fb5d4` | managed backup files (create/list/download/restore/delete) |
| V04 | `c1e228e` | pidfile-managed /service/ start\|stop\|log |
| V05 | `4b5a1ad` | retire session observation route/CLI/SPA |
| V06 | `996725b` | CLI v1.7.1 taxonomy (config/data parents, info, aliases) |
| V07 | this | SPA backup section + certification |

## Conformance

- `.venv/Scripts/python -m opal_look.contract_audit --strict` →
  CONFORMANT (70 paths / 105 operations, no legacy routes, service
  surface `GET /` + `GET /health` informational only).
- `.venv/Scripts/pytest` — full suite green.

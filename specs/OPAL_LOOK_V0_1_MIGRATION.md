# OPAL Look v0.1.0 migration ledger

Clean-cutover migration from `opal_look_v1.7.1.yaml` + kernel 1.7.1
(47 ops, 39 paths) to `opal_look_v0.1.0.yaml` + kernel 0.1.0
(45 ops, 35 paths). Strict audit: `RESULT: CONFORMANT`.

## Retired surfaces

- `GET /api/v1/info/`, `GET /api/v1/info/ping` — health is the single
  service information surface (`OpalHealthReport`).
- All `/api/v1/backup/*` (8 ops) — replaced by `config save/load/validate`.
- `PATCH /api/v1/setting/` — per-key `PUT`/`DELETE` only.
- CLI: `backup` group, `config engine update`, `config profile *`,
  `config setting update|patch`, `info version|ping|live|ready`,
  top-level `setting` aliases.

## Added surfaces

- `POST /api/v1/config/save|load|validate` — portable
  `OpalConfigSnapshot` (`settings` + `resources`: profiles, personas,
  engines, models). `save` is not a live mutation (no If-Match, no
  revision bump); the managed destination atomically replaces the
  single stored snapshot held in the `meta` table. `load` replaces the
  complete persistent configuration atomically under If-Match after
  validating the whole candidate; `validate` is non-mutating.
- Persona catalog: `GET|POST /api/v1/persona/`, `GET|PATCH|DELETE
  /api/v1/persona/{id}`, `POST .../validate`. Local catalog (`origin:
  local`), `voice_id` opaque to Look, `?enabled` filter, If-Match on
  catalog (create) and record (patch/delete) revisions.

## Changed semantics

- `GET /api/v1/health/` — merged `OpalHealthReport`: `name`, `version`,
  `api_version`, `status`, `live`, `ready` at top level; diagnostics
  (`engines`, `checks`, `database_ready`, etc.) moved under `details`.
  `active_profile_id` is now a string.
- Settings — `SettingRead` carries `configured_value`, `has_override`,
  `is_default`, `source` (default|persisted|dotenv|environment),
  `restart_required`, `pending_restart`, `warnings`. Env/`.env` values
  are a read overlay, no longer persisted at boot.
- Profiles — portable `OpalProfile` documents: string ids, required
  `shared` + `modules` compartments, closed envelopes. Foreign
  compartments are preserved verbatim and PATCH-restricted (422) to the
  receiving module's compartment; `modules.opal-look` is an explicit
  empty closed schema. `is_active: false` never deactivates by itself.
- `PATCH /api/v1/engine/{id}` — `minProperties: 1` (empty body 422);
  additional top-level keys are engine option values merged into the
  stored config and adapter-validated.

## Storage migrations

- `profiles` table rebuilt: `profile_id` INTEGER→TEXT, legacy flat
  fields (`model_id`, `task`, `settings`, `data`) migrate under the
  unrecognized `modules["opal-look-legacy"]` compartment (portable,
  preserved verbatim through save/load). Int ids stay addressable as
  their string form.
- `personas` table created; pre-cutover-era personas tables with a
  different column set rebuild into the new schema instead of being
  dropped.
- `meta.managed_snapshot` — the single managed config snapshot;
  `meta.desired_models` — the `resources.models` desired-state section
  (models are engine-federated; load performs no model actions).

## Caller migration notes

- `backup export` → `config save --out`; `backup import` →
  `config load --in`; managed archives → `config save`/`config load`.
- `info` consumers read `GET /api/v1/health/` (name/version/api_version
  top-level; diagnostics under `details`).
- Whole-map settings updates become per-key `PUT /api/v1/setting/{key}`.
- Profile documents are namespaced; clients must not write foreign
  compartments.

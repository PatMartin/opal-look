# OPAL Look v0.5.0 migration ledger

Clean-cutover migration from `opal_look_v0.1.0.yaml` + kernel 0.1.0
to `opal_look_v0.5.0.yaml` + kernel 0.5.0 (same surface: 45 ops,
35 paths). Strict audit: `RESULT: CONFORMANT`.

## Retired surfaces

- `x-opal-cli` everywhere: the kernel `x-opal-cli-format` extension is
  deleted and no operation (kernel- or module-owned) ships a descriptor;
  the look contract's `x-opal-cli-commands` index is gone with it. CLI
  command spelling is no longer contract-declared — the taxonomy lives
  in `opal_look_cli` as the established canonical mapping.
- CLI `info` group: kernel 0.5.0 health-probe descriptions direct the
  human-readable report to `service health`; `opal-look info health`
  is retired (no alias — clean cutover).

## Added surfaces

- `opal-look service health` — REST `GET /api/v1/health/` report
  (replaces `info health`; the live/ready probes remain machine-only,
  no CLI binding).
- `DELETE /api/v1/persona/{id}` now declares a `409` response
  (permissive addition; Look's local catalog has no referents, so the
  implementation still only returns 204/404/412/428).

## Changed semantics

- `OpalProfileModules`/`OpalProfileModulesPatch`: the declared empty
  compartment `opal-event` is renamed `opal-bus`
  (`OpalEventProfileNamespace` -> `OpalBusProfileNamespace`, still
  closed-empty — any member 422). `opal-event` is now an undeclared
  namespace: any well-formed object is accepted and preserved verbatim
  (`profiles._EMPTY_COMPARTMENTS` updated). No data migration — the
  old closed schema never permitted `opal-event` members, so stored
  compartments are `{}` and remain valid.
- Kernel health docs/examples renamed `opal-event` -> `opal-bus`;
  `details.stats` prose now references OPAL Bus. Look declares no
  health `details` members (`x-opal-health-details.members: {}`), so
  no payload change.

## Storage migrations

None. Schema, repositories and snapshot formats are unchanged;
`format_version` remains `1.0.0`.

## Caller migration notes

- `opal-look info health` -> `opal-look service health`.
- Clients declaring `x-opal-cli` bindings from the contract must read
  them from their own catalog now — the contract no longer publishes
  the extension.
- Profile tooling that knows declared compartments: `opal-event` is no
  longer schema-checked (preserved verbatim); `opal-bus` is the
  declared closed-empty compartment.
- Sibling services: upstream renamed opal-event -> opal-bus. The
  pinned adapter contract `openapi/engines/opal_look_yolo_v0.1.0.yaml`
  still carries orphaned `x-opal-cli` descriptors (all `$ref`s still
  resolve) until opal-look-yolo publishes its 0.5.0 rev. The opt-in
  event bridge targets the sibling event service by configured URL and
  is unaffected in code.

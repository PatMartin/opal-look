# Composite Vision OpenAPI Design Package

Draft domain contracts for **YOLO, RF-DETR, RT-DETR, D-FINE**, to be consumed by `opal-look` through its common engine/plugin abstraction. **No existing GitHub repository or current API was modified.**

## Contents

- `docs/VISION_ARCHITECTURE.md` — 35 ratified decisions, ownership, compatibility and rollout
- `openapi/shared/vision_kernel.yaml` — shared OpenAPI 3.1 schemas and reusable Path Items; not served standalone
- `openapi/engines/{yolo,rfdetr,rtdetr,dfine}.yaml` — independent, contract-first engine adapter APIs
- `docs/VISION_CLI.md` — unified and standalone Typer command trees, usage and REST mappings
- `docs/INTEGRATION_GAPS.md` — existing Look 1.7.1 API vs new design
- `tests/` — contract structure, references, option validation and suite conventions
- `build_contracts.py` — reproducibly regenerates the YAML files

## Authoritative kernel dependency

The package **does not vendor or modify** `opal_kernel.yaml`. To validate/bundle all external references, copy this package's `vision_kernel.yaml` into `opal-api/openapi/shared/` and the engine files into `opal-api/openapi/engines/`, alongside the *actual* existing `opal_kernel.yaml` from [PatMartin/opal-api](https://github.com/PatMartin/opal-api/blob/main/openapi/shared/opal_kernel.yaml).

The expected layout is:

```text
openapi/shared/opal_kernel.yaml  # existing, unchanged
openapi/shared/vision_kernel.yaml
openapi/engines/yolo.yaml
openapi/engines/rfdetr.yaml
openapi/engines/rtdetr.yaml
openapi/engines/dfine.yaml
```

`opal_look.yaml` is **not overwritten**. Integration requires an explicit migration review. This is a **draft specification**, not evidence that an engine implementation exists or supports a particular optional parameter.

## Tests

```bash
python -m pip install pyyaml jsonschema pytest
python -m pytest tests -q
# After adding the actual suite kernel to openapi/shared/:
python tests/check_contracts.py --strict
```

The default tests validate generated specs and known kernel component identities against a pinned manifest; they do **not** pretend to have the full upstream suite kernel. Strict mode additionally resolves every reference against the real file and checks the upstream SHA/structures. For a more complete OpenAPI conformance check, bundle with the repository's existing tooling and run its Spectral rules.

## Principles

- Suite-wide conventions in `opal_kernel.yaml`, vision domain objects in `vision_kernel.yaml`, engine-specific details in each engine contract.
- A capability that changes an existing behavior extends its typed options; a genuinely different behavior gets a distinct operation.
- No mandatory opal-devices, opal-flow or opal-look process for an independent engine adapter.
- Task-specific Typer commands are aliases for `predict --task` unless semantics genuinely differ.
- Capability gating is mandatory; no assumption that every engine implementation/model/runtime supports every nominal feature.

## Current verification

See `docs/VALIDATION_REPORT.md` for counts, test results and the exact limitation of the upstream dependency check.

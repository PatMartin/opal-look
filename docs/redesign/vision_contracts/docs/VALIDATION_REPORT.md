# Contract Validation Report

**Build:** composite vision draft `0.1.0-draft`  
**Inspected upstream:** OPAL kernel 1.7.1 from `PatMartin/opal-api`, SHA `0773c5fea4ac2dd4e96536e630ec9a26a5232ec5`  
**Suite source:** <https://github.com/PatMartin/opal-api/blob/main/openapi/shared/opal_kernel.yaml>

## Files generated

| File | Direct paths mounted | Non-OPAL operations validated locally | Local specialized schemas |
|---|---:|---:|---:|
| `openapi/shared/vision_kernel.yaml` | 0 (reusable only) | 26 reusable Path Items | 35 |
| `openapi/engines/yolo.yaml` | 38 | 31 | 13 |
| `openapi/engines/rfdetr.yaml` | 35 | 28 | 10 |
| `openapi/engines/rtdetr.yaml` | 35 | 28 | 10 |
| `openapi/engines/dfine.yaml` | 35 | 28 | 10 |

Counts of non-OPAL operations exclude mounted OPAL kernel Path Items whose implementation is defined upstream. Engine-specific `predict/train/validate/export/benchmark` are specialized typed request operations, not duplicate API endpoints.

## Executed validation

- [x] YAML parse for all five files
- [x] OpenAPI `3.1.0` declarations and basic document structure
- [x] All local `$ref`s and references to `vision_kernel.yaml` resolve
- [x] OPAL external symbols match the available upstream-kernel component manifest
- [x] Per-document operation IDs are unique among locally resolvable operations
- [x] All locally resolved `{path_parameters}` have required path parameter definitions
- [x] Correlation response-header declarations checked on locally resolved success/error responses
- [x] REST operations have canonical `x-opal-cli` declarations
- [x] All four engine contracts have typed `engine_options` on their five major workflows
- [x] Unknown engine options rejected by JSON Schema
- [x] YOLO-specific `track/tune/solutions` remain separate
- [x] No duplicate task-specific `/segment/` endpoint in the other three engines
- [x] Kernel file is reusable components only (`paths: {}`)
- [x] Explicit model install is a separate operation from predict

**Pytest result:** 28 passed.

## Not yet validated

- [ ] **Full resolution and bundling against the actual `opal_kernel.yaml` file.** The verified upstream content was inspected with GitHub, but the full file was not available in the local generation container. Tests use a manifest of its actual component names when file bytes are unavailable, and report this limitation explicitly.
- [ ] Full OpenAPI 3.1 schema validation with the repo's chosen OpenAPI validator and Spectral configuration.
- [ ] End-to-end conformance against live YOLO, RF-DETR, RT-DETR, or D-FINE REST adapters.
- [ ] New unified `opal-look` API compatibility testing, which requires explicit reconciliation with the existing v1.7.1 application contract.
- [ ] Backend-specific parameter support verified on every supported installed model and runtime.
- [ ] Security testing for remote media fetch, credentials, artifact retrieval and deployment auth.

## How to complete upstream compatibility validation

In `opal-api`, add the proposed files under `openapi/shared/` and `openapi/engines/` *alongside* the existing `openapi/shared/opal_kernel.yaml` without replacing the suite kernel. Then:

```bash
python tests/check_contracts.py --strict
python -m pytest tests -q
# Run opal-api's native npm run bundle and Spectral/lint workflow on each new service document.
```

**Interpretation:** The contract package is a testable design draft. It should not yet be treated as implementation-ready or fully bundled against the upstream kernel.

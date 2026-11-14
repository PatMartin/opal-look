# Integration delta: proposed composite vision vs existing opal-look v1.7.1

This note deliberately avoids publishing a conflicting replacement for the existing `openapi/opal_look.yaml`. Inspected from `PatMartin/opal-api` main on 2026-11-11.

| Existing Look functionality | Present in inspected spec? | Composite vision action |
|---|---:|---|
| `/api/v1/engine/` + engine item | Yes; uses suite kernel | Reuse; add plugin/instance discovery only after diff |
| `/api/v1/model/` + item | Yes | Preserve routes; add federated metadata semantics without central weights |
| `/api/v1/capabilities/` | Yes | Extend to model/runtime/instance support while maintaining compatibility |
| `/api/v1/source/` + source status/probe | Yes | Preserve; prefer optional opal-devices lookup, never require it |
| `/api/v1/pipeline/` + validate | Yes | Reconcile linear-first DAG, typed edges, merge policies and failure handling |
| `/api/v1/session/` + SSE stream | Yes | Reuse; don't introduce parallel `/streams` lifecycle unless real design gap |
| `/api/v1/job/` + cancel | Yes | Extend only when engine delegation needs a new job kind |
| `/api/v1/analyze/` and image analysis | Yes | Map unified `predict` and task aliases without duplicate endpoints |
| `/api/v1/artifact/`, media, captures | Yes | Reuse artifact store with access/retention requirements |
| `/api/v1/zone/`, rules, monitors, recordings | Yes | Reuse; do not duplicate analytics state in engine adapters |
| Training, export, engine-managed downloads | Explicitly excluded in current Look description | Keep engine-owned; unified CLI can delegate after a deliberate contract decision |
| Plugin discovery and runtime discovery | Not verified as dedicated resources | Proposed additions; gap analysis needed |
| Federated model metadata cache | Not verified as dedicated behavior | Proposed augmentation, not automatic replacement |

The standalone adapter contracts in this package are safe to develop separately; this integration delta is a review checklist, not a patch.

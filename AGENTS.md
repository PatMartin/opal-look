# AGENTS.md — OPAL LOOK

> Permanent engineering guardrails for coding agents working in `opal-look`.
> These instructions govern ongoing development, not a one-time remediation plan.
> Follow the currently approved OPAL contracts; report discrepancies rather than
> attempting contract-version reconciliation or redesign without authorization.

## 1. Purpose and boundaries

OPAL LOOK is the visual observation service in the OPAL ecosystem. It accepts
video/image sources, manages capture and stream lifecycles, produces frames and
visual artifacts, and exposes observations through REST, a CLI, and a browser UI.
It can optionally invoke compatible vision engines to analyze frames.

**LOOK owns:**
- Source configuration and access policy; camera and image-source handling.
- Capture, decoding, frame identity, stream lifecycle, and bounded fan-out.
- Live video endpoints, snapshots, optional annotation, stream metrics, and
  metadata/event streams as defined by the contract.
- Selection and invocation of compatible detection/inference engines.
- Normalizing engine outputs into LOOK's public response/event contracts.
- Its own health, settings, portable configuration, and observability.

**LOOK does not own:**
- YOLO/RF-DETR/RT-DETR/D-FINE model algorithms, weights, installation,
  or engine-native inference implementations.
- General-purpose playback/player interfaces; keep video *delivery* distinct
  from interactive viewing, which may be handled by a separate SHOW component.
- General event rule evaluation, automation execution, or orchestration; BUS
  and other consumers may subscribe to LOOK observations.
- Microphone capture, transcription, speech synthesis, or reasoning.
- A mandatory shared device registry or central coordinator.

A video-only stream must remain useful **without any AI engine installed**.
Engine unavailability may disable inference, but must not unnecessarily disable
independent capture, snapshots, or video delivery.

## 2. The eight OPAL design tenets

1. **Boundary Elasticity** — Preserve logical contracts while allowing
   implementations to run in-process, through local sockets, or across a network.
   Deployment boundaries are choices, not product limitations.
2. **Independent Utility** — Every capability should deliver value on its own.
   LOOK must not need THINK, LISTEN, SAY, BUS, SHOW, or a central registry just
   to observe a camera.
3. **Additive Composition** — Combine components via contracts without changing
   their internals. Integration is optional and must not redefine ownership.
4. **Economic Accessibility** — Prioritize useful operation on affordable local
   hardware and commodity cameras; do not require expensive GPUs or cloud APIs
   for the basic observation path.
5. **Progressive Capability** — Begin with simple capture and inspection;
   enable inference, annotation, acceleration, and analytics when resources exist.
6. **Interchangeable Parts** — Standardize interfaces, not implementations.
   Engines, capture adapters, transports, and compute backends should be
   replaceable behind stable contracts.
7. **Discover and Use** — **Discover what exists. Use what is available.
   Require nothing else.** Capability discovery must not imply dependence on
   absent or disabled integrations.
8. **Extend the Right Surface** — **If a capability performs an existing
   operation differently, extend its parameters. If it performs something
   meaningfully different, extend the API.** Avoid duplicated endpoints and
   special cases for variations that belong in existing operations.

## 3. Architecture and responsibility boundaries

- Keep capture/decode, stream management, artifacts, engine adapters, REST,
  CLI, UI, and persistence separable and testable.
- Do not move engine-native model-management or inference code into LOOK simply
  to simplify deployment. Support both embedded and remote integrations where
  compatible with the shared engine interface.
- Keep a **synthetic** or deterministic test path for contract verification,
  but never represent synthetic detections as actual model recognition.
- Treat source, stream, frame, engine, model, and inference execution as
  distinct identities. Propagate available context rather than inventing it.
- Preserve frame order, identity, timestamps, dimensions, and provenance across
  capture, inference, overlays, and emitted observations.
- Avoid introducing an entire streaming framework, job system, registry, or
  event rule engine when a small extension of the existing architecture suffices.
- Maintain explicit ownership of resource cleanup when a stream stops, a client
  disconnects, an engine times out, or the service shuts down.

## 4. Stream, frame, and artifact behavior

- The service owns stream lifecycle, not a downstream engine or viewer.
- A single capture pipeline should be reusable by compatible consumers when
  doing so avoids duplicated camera connections and decode work.
- Apply bounded queues and explicit backpressure. A slow inference engine,
  SSE client, MJPEG consumer, or snapshot requester must not cause unbounded
  memory growth or indefinitely stall capture.
- Document and test drop policies, disconnect behavior, retries, and
  cancellation. Never imply exactly-once events or guaranteed replay unless
  the contract explicitly provides them.
- Distinguish live-only media (e.g., MJPEG and snapshots) from any bounded
  SSE replay mechanism in the approved contract.
- Treat overlay/annotation as optional presentation output; original frames
  and inference results must remain independently usable when supported.
- Make artifact formats, MIME types, dimensions, sampling, timestamps, and
  lifecycle explicit. Avoid hidden persistence or unbounded retention.
- Preserve honest stream states, errors, and readiness even when the camera
  cannot connect or no inference engine is available.

## 5. Inference engines and model contracts

- Engines are optional, discoverable implementations with explicit capability,
  availability, supported-task, device, and option metadata.
- Use standardized engine interfaces and normalized outputs for detection and
  other supported tasks. Preserve clearly namespaced native results only where
  the contract permits.
- Never assume every engine supports detection, segmentation, classification,
  pose, OBB, a particular device, or a particular model.
- Validate task support, model/engine compatibility, required inputs, and
  engine-specific options **before** invoking inference. Reject unsupported
  options rather than silently ignoring them.
- Honor explicit engine/model selection; do not silently select a different
  engine or model when fallback is unspecified.
- Keep model discovery, load/unload, runtime residency, and compute-device
  details within the owning engine; LOOK may expose or proxy them through its
  public interface.
- Do not download weights, install engines, create devices, or expose raw
  filesystem paths as side effects of discovery.
- Bound engine calls by concurrency, time, memory where feasible, and failure
  policy. A remote engine outage must be isolated from unrelated video streams.
- Normalize coordinates, class labels, scores, frame metadata, and errors
  consistently; do not fabricate inference confidence or capability.

## 6. REST, OpenAPI, CLI, and UI fidelity

- The approved **OpenAPI 3.1 contract** is the public source of truth;
  shared OPAL Kernel definitions govern common semantics.
- REST implements the contract. The Typer CLI and browser UI are clients of
  the REST surface, not alternate implementations of business logic.
- Keep REST/CLI/UI behavior aligned for supported operations, argument types,
  requiredness, response handling, and error semantics.
- As suite-wide CLI derivation advances, derive command hierarchy from
  OpenAPI paths and actions from `operationId`; derive options and validation
  from standard OpenAPI parameters and schemas.
- **Do not add** `x-opal-cli`, `x-opal-cli-format`, per-operation command
  mappings, or equivalent CLI-specific contract metadata. Existing legacy
  bindings, if any, must not be removed until a separately approved migration
  proves compatibility.
- Preserve existing CLI spellings and aliases unless a change is explicitly
  justified and approved. Do not rename `operationId` merely for a prettier CLI.
- Use standard OPAL request/transaction/session/causation IDs, `OpalError`,
  health semantics, HTTP status codes, and configuration preconditions.
  Context IDs are trace data, never authorization credentials.
- Keep settings and config save/load/validate consistent with the shared
  suite contract; strong ETags and `If-Match` protect mutations where required.
- Escalate contract ambiguities and missing operations; do not silently
  extend a public API or adjust contract versions.
- Avoid inventing interface parity where the approved contract intentionally
  exposes a transport-specific feature (such as SSE or MJPEG).

## 7. Security and privacy

- Treat RTSP URLs, userinfo, image paths, client-provided URLs, metadata, and
  engine output as untrusted inputs.
- Never log, echo, embed in errors, or persist raw camera credentials.
  Resolve credential references through controlled configuration only.
- Keep authentication mandatory for non-loopback exposure according to
  the approved service security policy; do not use correlation IDs as tokens.
- Default remote image/URL fetching to **off**, or enforce explicit allowlists
  and protections against SSRF, redirects, DNS rebinding, and private-network
  bypass. Bound downloads by time, bytes, and decoded dimensions.
- Validate filesystem access and path traversal. Avoid arbitrary local file
  reads, especially when requests arrive over the network.
- Do not log frames, sensitive images, user-provided URLs, or model-native
  payloads by default. Minimize retained data.
- Do not execute model output as shell commands, Python, URL requests, or
  privileged actions. Observation and action execution are separate services.
- Secrets belong in environment/configuration references, not code, exported
  snapshots, logs, or test fixtures.

## 8. Configuration, deployment, and performance

- Local-first, sensible defaults. Basic capture and observation must not depend
  on internet access or proprietary hosted inference.
- Respect the documented configuration precedence; existing environment
  values take precedence over `.env`, which takes precedence over defaults.
  Do not silently change persistence/seed behavior.
- Preserve standalone usability; integrate with BUS, SHOW, inference engines,
  or future device registries only as optional additions.
- Support practical CPU-only operation; treat GPU acceleration as an optional
  capability, not a universal assumption.
- Do not block the event loop with camera decode or heavy inference. Bound work,
  buffering, concurrent streams, and inference admission.
- Define cleanup for open RTSP sessions, capture workers, memory buffers,
  temporary artifacts, remote requests, and engine handles.
- Prefer observable, deterministic degradation to hidden retries or fallback.
- Keep configuration snapshots portable; omit secrets, live frames, large
  binaries, volatile stream state, and runtime caches.

## 9. Compatibility and scope discipline

- Preserve behavior unless the task explicitly authorizes changing it.
- Do not perform contract-version reconciliation, broad redesign, repository
  restructuring, or cosmetic refactoring as incidental work.
- Compare requested work against the established ownership boundaries and
  call out violations or accidental complexity directly.
- Prefer small composable changes over introducing new abstractions.
- When a design change is necessary, propose separately numbered options,
  state tradeoffs and complexity, recommend one, and obtain approval for
  breaking changes before implementation.
- Document intentional deviations from existing OPAL conventions rather than
  silently creating LOOK-specific standards.
- Do not confuse a successful mock test with successful real-camera or
  real-model operation.

## 10. Required verification

For every meaningful code or contract change, test the affected behavior and
the surrounding boundaries. Prioritize:

- Contract validation and strict REST/API conformance audits.
- Source validation, credential redaction, network restrictions, and auth.
- Stream start/stop, reconnect/failure handling, teardown, and idempotency.
- Bounded queues, backpressure, slow-client isolation, concurrency, and cleanup.
- SSE frame/terminal behavior, replay limits (if offered), MJPEG, and snapshots.
- Engine/model availability, unsupported tasks/options, timeouts, and outages.
- Frame identity and normalized inference result fidelity.
- CLI/REST parity and browser UI correctness for changed operations.
- Pure video operation without an inference engine.
- Deterministic synthetic tests and optional real RTSP/YOLO integration tests.

Use the repository's current pytest and contract-audit entry points. Report
which tests were actually run, not historical counts. Keep hardware/network
integration tests explicitly opt-in unless the project already provides safe,
controlled fixtures. Never claim to have tested a live camera or model unless
you did so.

## 11. Agent execution and reporting

When implementing a requested change:

1. State the requested scope and relevant contracts before editing.
2. Report what was changed and exactly which files were touched.
3. Give a **subjective estimated defect probability (%)**, with justification;
   do not present it as measured statistical risk.
4. Report test commands and **passed / failed / skipped / not-run** counts.
5. Explain how the maintainer can reproduce the verification.
6. Identify remaining uncertainty, contract drift, and potential test gaps.
7. If work is staged, report **Step N of M**, what is complete, and the next
   proposed step. Stop for approval only when the workflow requires it.
8. Ask only necessary clarifying questions; provide concise options,
   complexity, pros/cons, and a recommendation when choices affect design.
9. Challenge flawed assumptions or unnecessary complexity respectfully and
   specifically; do not agree merely to be agreeable.
10. Never fabricate execution evidence, commit status, implementation coverage,
    or integration results.

**Guiding principle:** Explore without limits. Design with discipline.
Implement with restraint. Validate with evidence.

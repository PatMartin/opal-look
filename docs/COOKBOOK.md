# OPAL Look Cookbook

This cookbook is a collection of practical, copy/pasteable workflows for
OPAL Look v1.5.

Every fenced shell block has GitHub's built-in **Copy** button in the upper
right. Run the commands from a shell with the OPAL Look environment installed.
Use either `opal look ...` or `opal-look ...`; they are identical clients.

## Before You Start

Start the service in one terminal:

```bash
opal serve
```

Run the following in another terminal. Set `LOOK` when the service is not on
the default local address, and add `Authorization: Bearer ...` outside this
document when the service requires a token.

```bash
export LOOK=http://127.0.0.1:8000
alias look='opal look --url "$LOOK"'

look info ready
look engine list
look config model list
```

The included `synthetic-vision` model produces deterministic,
detection-shaped test observations. It is useful for integrating workflows,
but it does **not** identify real people, vehicles, animals, or hazards. A
real model adapter is required before using any workflow below to make
real-world decisions.

Most recipes need a source and a stages-only pipeline. This small bootstrap
creates a reusable image source and detection pipeline:

```bash
look data media upload ./sample.jpg
# Copy the returned id into MEDIA_ID.
export MEDIA_ID=media-REPLACE_ME

look source add --body '{
  "id":"sample-image",
  "name":"Sample image",
  "kind":"media",
  "locator":"'"$MEDIA_ID"'"
}'

look config pipeline add --body '{
  "id":"detect",
  "name":"Detection pipeline",
  "stages":[{
    "id":"detect-stage",
    "kind":"inference",
    "model_id":"synthetic-vision",
    "task":"detection"
  }]
}'
```

## 20 Things OPAL Look Can Do On Its Own

These workflows use only OPAL Look's service, REST API, CLI, local files, and
supported cameras. They focus on a visual-observation capability that a
general automation, speech, or event package cannot provide by itself.

### 1. Turn a photograph into structured visual observations

Use a pipeline to turn a stored picture into typed observation records.

```bash
look analyze run --body '{
  "pipeline_id":"detect",
  "source":{"media_id":"'"$MEDIA_ID"'"},
  "retention":{"persist_observations":true}
}'
```

### 2. Test an image-processing integration without a camera

The image endpoint accepts a local file directly, making it useful in CI,
fixtures, and developer demos.

```bash
look analyze image ./sample.jpg \
  --request '{"pipeline_id":"detect","retention":{"persist_observations":false}}'
```

### 3. Build a reusable visual pipeline

Pipelines let multiple sources and jobs share an immutable intent: which
model and processing stages should run.

```bash
look config pipeline validate --body '{
  "id":"quality-check",
  "name":"Quality check",
  "description":"Reusable test detection pipeline",
  "stages":[{"id":"infer","kind":"inference","model_id":"synthetic-vision","task":"detection"}]
}'
look config pipeline add --body '{
  "id":"quality-check",
  "name":"Quality check",
  "stages":[{"id":"infer","kind":"inference","model_id":"synthetic-vision","task":"detection"}]
}'
```

### 4. Keep a named RTSP camera inventory

Register camera connection details once, then use the stable source ID in
monitoring, capture, recording, and analysis workflows.

```bash
look source add --body '{
  "id":"driveway",
  "name":"Driveway camera",
  "kind":"rtsp",
  "locator":"rtsp://camera.example.invalid:554/stream1",
  "enabled":true
}'
look source probe driveway
look source status driveway
```

### 5. Save one frame from a live source

This is a quick evidence or troubleshooting snapshot without running a
long-lived monitor.

```bash
look source frame driveway --out driveway-frame.jpg
file driveway-frame.jpg
```

### 6. Save an MJPEG inspection stream

Capture a bounded portion of a live view to inspect a camera or pipeline
overlay offline.

```bash
look sources view driveway \
  --pipeline detect \
  --out driveway-preview.mjpeg \
  --max-bytes 5000000
```

### 7. Run a finite pipeline session

Sessions expose runtime state, observations, a preview stream, and counters
for a processing run.

```bash
look session start --body '{
  "source_id":"sample-image",
  "pipeline_id":"detect",
  "options":{"max_frames":1},
  "retention":{"persist_results":true}
}'
look session list
```

### 8. Follow one session's observation stream

Use server-sent events to observe a session as it changes state and emits
observations. Stop with `Ctrl-C`.

```bash
export SESSION_ID=session-REPLACE_ME
look session stream "$SESSION_ID"
```

### 9. Download a bounded live session preview

Preview is useful when a client needs frames but should not be given camera
credentials or direct camera network access.

```bash
look session preview "$SESSION_ID" --out session-preview.mjpeg --max-bytes 5000000
```

### 10. Define a polygon region of interest

Zones express source-relative geometry once so rules can refer to it by ID.

```bash
look config zone add --body '{
  "id":"front-door",
  "source_id":"driveway",
  "name":"Front door area",
  "kind":"polygon",
  "points":[
    {"x":0.10,"y":0.20},
    {"x":0.80,"y":0.20},
    {"x":0.80,"y":0.95},
    {"x":0.10,"y":0.95}
  ],
  "enabled":true
}'
```

### 11. Define a virtual tripwire

A line zone can express a crossing boundary such as a gate, door, aisle, or
restricted threshold.

```bash
look config zone add --body '{
  "id":"gate-line",
  "source_id":"driveway",
  "name":"Gate threshold",
  "kind":"line",
  "points":[{"x":0.48,"y":0.05},{"x":0.48,"y":0.95}]
}'
```

### 12. Persist a visual rule separately from the camera monitor

Rules make visual intent inspectable, editable, and reusable. With a
real tracking-capable model, this can represent entry, exit, dwell, and
count conditions.

```bash
look config rule add --body '{
  "id":"door-entry",
  "name":"Object enters the front door zone",
  "source_id":"driveway",
  "zone_id":"front-door",
  "kind":"enters_zone",
  "class_filters":["person"],
  "cooldown_ms":30000,
  "capture_on_match":true,
  "enabled":true
}'
```

### 13. Create an always-on monitor

Monitors continuously process a live source with a pipeline and evaluate its
enabled rules.

```bash
look config monitor add --body '{
  "id":"driveway-watch",
  "name":"Driveway watch",
  "source_id":"driveway",
  "pipeline_id":"detect",
  "enabled":true,
  "restart_policy":"on_failure"
}'
look config monitor show driveway-watch
```

### 14. Capture evidence linked to a session or observation

Use captures for a durable image record. Add `--annotate` only when the
session or observation provides annotation context.

```bash
look source capture driveway --retain --session "$SESSION_ID"
look data capture list --source driveway
look data capture download capture-REPLACE_ME --out evidence.jpg
```

### 15. Record a bounded camera clip

Recordings create a managed output that can later be exposed as an artifact.

```bash
look data recording start --source driveway --pipeline detect --duration 30
look data recording list
# After it finishes:
look data artifact list --kind video
look data artifact download artifact-REPLACE_ME --out driveway-30s.mjpeg
```

### 16. Submit offline video analysis as a job

Jobs decouple expensive or long-running media processing from the caller.

```bash
look data media upload ./shift.mp4
# Copy the response id into VIDEO_ID.
export VIDEO_ID=media-REPLACE_ME

look data job submit --body '{
  "kind":"analyze_video",
  "media_id":"'"$VIDEO_ID"'",
  "pipeline_id":"detect"
}'
look data job list
```

### 17. Export annotated media as an artifact

Use the job resource for an asynchronous output and download its produced
artifact rather than relying on a legacy media-content endpoint.

```bash
look data job submit --body '{
  "kind":"export_annotated_video",
  "media_id":"'"$VIDEO_ID"'",
  "pipeline_id":"detect"
}'
look data artifact list --kind video
```

### 18. Switch a camera fleet between named processing profiles

Profiles package a pipeline choice and operational options for a named
deployment posture such as "day", "night", or "privacy-first".

```bash
look config profile add --body '{
  "name":"Night watch",
  "pipeline_id":"detect"
}'
# Copy the numeric id returned by the command into PROFILE_ID.
export PROFILE_ID=1
look config profile activate "$PROFILE_ID"
look config profile show "$PROFILE_ID"
```

### 19. Export a portable visual deployment configuration

Export creates a reviewable transfer artifact for pipelines, sources,
profiles, zones, rules, and monitor definitions.

```bash
look backup export > look-config.json
look backup validate --file look-config.json
```

### 20. Inspect visual-service health and load before adding cameras

Use health, capabilities, and metrics to check that a deployment has the
expected runtime support before automating it.

```bash
look info health
look info capabilities
look info metrics
look info events
```

## 20 Cross-Module OPAL Workflows

The workflows below combine Look with the wider OPAL ecosystem:

- **OPAL Event** distributes facts and triggers automations.
- **OPAL Listen** turns spoken intent into commands or context.
- **OPAL Talk** presents a response to a human.
- **OPAL Think** reasons over observations, history, policy, and context.

The sibling modules have independent installation, authentication, and API
contracts. The examples therefore keep the **fully runnable Look CLI** in
the snippets and label the integration boundary rather than inventing CLI
syntax for a module that may be deployed differently. Replace the placeholder
URLs and automation adapters with the endpoints configured by your OPAL
deployment. Do not wire a synthetic model to a physical-world action.

### 21. Spoken "is the driveway clear?" assistant

**Listen** captures the question; **Think** chooses a current-view request;
**Look** supplies observations; **Talk** answers in natural language.

```bash
# Look step called by the Think action handler:
look analyze run --body '{
  "pipeline_id":"detect",
  "source":{"source_id":"driveway"},
  "retention":{"persist_observations":false}
}'

# Hand the returned JSON to your Think policy, then to Talk.
```

### 22. Voice-requested visual evidence

A person asks Listen to "take a picture of the loading bay"; Think resolves
the authorized source; Look captures it; Talk confirms the saved evidence ID.

```bash
look source capture loading-bay --retain
look data capture list --source loading-bay
look data capture download capture-REPLACE_ME --out loading-bay-evidence.jpg
```

### 23. Gate-crossing announcement

Look detects a line crossing, Event distributes `opal.look.rule.matched`,
Think applies quiet-hour policy, and Talk announces an approved alert.

```bash
look config zone add --body '{
  "id":"gate","source_id":"driveway","name":"Gate",
  "kind":"line","points":[{"x":0.5,"y":0.0},{"x":0.5,"y":1.0}]
}'
look config rule add --body '{
  "id":"gate-crossing","name":"Gate crossing","source_id":"driveway",
  "zone_id":"gate","kind":"line_crosses","cooldown_ms":30000,"enabled":true
}'
look config monitor add --body '{
  "id":"gate-monitor","name":"Gate monitor","source_id":"driveway",
  "pipeline_id":"detect","enabled":true
}'
```

### 24. Delivery arrival workflow

Look identifies an event candidate, Event fans it out, Think correlates it
with an expected delivery, and Talk tells the right person. Use a retained
capture as the audit attachment.

```bash
look config rule add --body '{
  "id":"delivery-evidence","name":"Delivery evidence","source_id":"driveway",
  "kind":"object_appears","class_filters":["package"],
  "capture_on_match":true,"cooldown_ms":60000,"enabled":true
}'
look data capture list --source driveway
```

### 25. Privacy-aware visitor announcement

Think can decide whether policy permits an announcement based on time, user
preferences, and location; Look contributes only an event and capture ID.

```bash
# `privacy-first` must already exist. Copy its numeric id from `config profile list`.
export PRIVACY_PROFILE_ID=2
look config profile activate "$PRIVACY_PROFILE_ID"
look config monitor update driveway-watch --body '{"profile_id":"'"$PRIVACY_PROFILE_ID"'"}'
look info metrics
```

### 26. Voice-controlled camera profile

Listen recognizes "switch cameras to night watch"; Think authorizes it; Look
activates the deployment profile; Talk confirms the change.

```bash
look config profile activate "$PROFILE_ID"
look config profile show "$PROFILE_ID"
look config monitor list
```

### 27. Accessible "what happened?" timeline

Event maintains a cross-module timeline, Think summarizes the relevant
observations, and Talk reads it aloud. Look supplies retained observations.

```bash
look data observation list
look data observation show observation-REPLACE_ME
look data artifact list
```

### 28. Escalate only after repeated visual events

Look applies a per-rule cooldown; Event carries each fact; Think implements
the higher-level "three events in ten minutes" escalation; Talk communicates
only the approved escalation.

```bash
look config rule update door-entry --body '{
  "cooldown_ms":60000,
  "capture_on_match":true,
  "enabled":true
}'
look config rule show door-entry
```

### 29. Ask for a live view by voice, without exposing RTSP credentials

Listen requests a view, Think checks authorization, Look produces a
bounded preview, and a UI or Talk companion shares the approved link or
summary. Camera credentials never leave Look.

```bash
look session start --body '{
  "source_id":"driveway","pipeline_id":"detect","auto_start":true
}'
look session preview session-REPLACE_ME --out authorized-preview.mjpeg \
  --max-bytes 5000000
```

### 30. Smart meeting-room occupancy assistant

Look provides visual occupancy observations, Event distributes changes,
Think combines bookings and policy, Listen accepts a question, and Talk
answers whether the room can be used.

```bash
look source add --body '{
  "id":"room-a","name":"Room A","kind":"rtsp",
  "locator":"rtsp://room-a.example.invalid/stream"
}'
look config monitor add --body '{
  "id":"room-a-occupancy","name":"Room A occupancy",
  "source_id":"room-a","pipeline_id":"detect","enabled":true
}'
```

### 31. Warehouse exception triage

Look watches a bay, Event opens a workflow, Think combines inventory context,
and Talk asks a nearby operator a focused follow-up question.

```bash
look source capture loading-bay --retain
look data recording start --source loading-bay --pipeline detect --duration 60
look data artifact list --kind video
```

### 32. Assisted elder-care check-in

With explicit consent and careful privacy controls, Look can produce a
low-level observation; Think evaluates a wellbeing policy; Event records
the fact; Talk asks a non-alarming check-in question.

```bash
look config profile activate privacy-first
look analyze run --body '{
  "pipeline_id":"detect",
  "source":{"source_id":"living-room"},
  "retention":{"persist_observations":true}
}'
```

### 33. Robot handoff with visual verification

Think plans a handoff, Look checks the designated handoff zone, Event informs
the robot controller, and Talk tells a nearby human whether intervention is
needed.

```bash
look config zone add --body '{
  "id":"handoff-zone","source_id":"dock","name":"Handoff zone",
  "kind":"polygon",
  "points":[{"x":0.2,"y":0.2},{"x":0.8,"y":0.2},{"x":0.8,"y":0.8},{"x":0.2,"y":0.8}]
}'
look config rule add --body '{
  "id":"handoff-arrival","name":"Arrival at handoff zone","source_id":"dock",
  "zone_id":"handoff-zone","kind":"enters_zone","enabled":true
}'
```

### 34. Safety incident evidence bundle

Look retains a capture and recording, Event ties them to an incident,
Think composes a concise narrative, and Talk presents a human-readable
status update.

```bash
look source capture driveway --retain
look data recording start --source driveway --pipeline detect --duration 120
look data capture list --source driveway
look data artifact list
```

### 35. Natural-language configuration review

An administrator asks Listen to explain the active visual policies; Think
reads Look configuration and produces a plain-language review for Talk.

```bash
look backup export > current-look.json
look backup validate --file current-look.json
look config profile list
look config rule list
look config zone list
```

### 36. Cross-site incident replay

Look exports a portable setup from one site; Think checks local policy;
Event records the approved rollout; Talk reports status to operators.

```bash
look backup export > site-a-look.json
look backup validate --file site-a-look.json

# On the receiving Look deployment:
opal look backup import --file site-a-look.json
```

### 37. Conversational video-job status

Listen receives "is yesterday's shift footage ready?"; Think identifies the
job; Look returns its progress and artifacts; Talk gives the answer.

```bash
look data job list
look data job show job-REPLACE_ME
look data artifact list --job job-REPLACE_ME
look data artifact download artifact-REPLACE_ME --out shift-review.mjpeg
```

### 38. Graceful degraded-mode assistant

When Look reports a unavailable camera or queued job, Event informs the
system, Think selects a safe fallback, and Talk explains the limitation
instead of making up an observation.

```bash
look info ready
look source status driveway
look info metrics
look info events
```

### 39. Human-approved actuator proposal

Look emits an observation, Think proposes but does not execute an action,
Talk asks a person for confirmation, and Event sends the confirmed command
to a separate actuator integration. Look remains an observer, never an
actuator.

```bash
look session stream session-REPLACE_ME
# Feed the resulting observation event to Think; require a separate,
# authenticated human approval before any actuator integration runs.
```

### 40. Daily visual operations briefing

Look provides metric and observation inputs, Event supplies a shared timeline,
Think generates a prioritized summary, Listen accepts follow-up questions,
and Talk delivers the briefing.

```bash
look info metrics
look data observation list
look data job list
look config monitor list
look info events
```

## Operational Notes

- Put `--url "$LOOK"` before the resource group, as shown in the `look` alias.
- The CLI fetches ETags and sends `If-Match` automatically for its mutation
  commands. Use the CLI rather than hand-written `curl` when you want that
  protection.
- Stop infinite SSE streams with `Ctrl-C`; for example,
  `look session stream SESSION_ID`.
- `extract_clip` currently returns an honest `422` because there is no clip
  decoder. `analyze_video` and annotated-media output should be tested with
  media supported by the deployment.
- Event publication is optional and best-effort. Check `look info events`;
  configure the event transport before relying on Event-driven workflows.
- In production, secure Look and every sibling OPAL service independently,
  give Think only the data it needs, and require explicit human authorization
  for actions with safety, privacy, access-control, or financial impact.

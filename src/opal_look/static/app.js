/* OPAL Look SPA v1.5 — thin REST client, no business logic. */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const sec = id => $(`#sec-${id}`);
let _abort = null;            // AbortController for open streams
let _bearer = sessionStorage.getItem("opal_token") || "";

function toast(msg, err = false) {
  const d = document.createElement("div");
  d.className = "toast" + (err ? " err" : "");
  d.textContent = msg;
  $("#toast").append(d);
  setTimeout(() => d.remove(), 6000);
}

function _auth() {
  // Bearer is kept in memory/session only — never in URLs or persisted
  // beyond the tab's session.
  return _bearer ? { "Authorization": `Bearer ${_bearer}` } : {};
}

async function api(method, path, { body, raw } = {}) {
  const opts = { method, headers: { ..._auth() } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  const etag = resp.headers.get("etag");
  if (etag) $("#etag").textContent = `ETag ${etag.slice(0, 18)}…`;
  if (raw) {
    if (!resp.ok) await _raise(resp);
    return resp;
  }
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    const err = data?.error
      ? `${resp.status} ${data.error.code}: ${data.error.message}`
      : `${resp.status}`;
    toast(err, true); throw new Error(err);
  }
  return data;
}
async function _raise(resp) {
  let msg = `${resp.status}`;
  try { const d = await resp.json(); if (d.error) msg = `${resp.status} ${d.error.code}: ${d.error.message}`; } catch {}
  toast(msg, true); throw new Error(msg);
}

async function mutate(method, path, body, etagOf) {
  let etag = '"*"';
  try { const r = await fetch(etagOf || path, { headers: _auth() });
        etag = r.headers.get("etag") || etag; } catch {}
  const resp = await fetch(path, {
    method,
    headers: { "If-Match": etag, "Content-Type": "application/json", ..._auth() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    const err = data?.error ? `${resp.status} ${data.error.code}: ${data.error.message}` : `${resp.status}`;
    toast(err, true); throw new Error(err);
  }
  return data;
}

/* Abortable streaming fetch (MJPEG/SSE); cancelled on navigation. */
async function stream(path, onEvent) {
  if (_abort) _abort.abort();
  _abort = new AbortController();
  const resp = await fetch(path, { headers: _auth(), signal: _abort.signal });
  if (!resp.ok) { await _raise(resp); return; }
  const rd = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await rd.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      onEvent(buf.slice(0, i));
      buf = buf.slice(i + 2);
    }
  }
}
function stopStreams() { if (_abort) { _abort.abort(); _abort = null; } }

const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const _list = async (h, p) => `<h3>${h}</h3><pre>${esc(JSON.stringify(await api("GET", p), null, 2))}</pre>`;

async function render(id) {
  stopStreams();
  document.querySelectorAll("main section").forEach(s => s.innerHTML = "");
  const fn = SCREENS[id]; if (fn) await fn(sec(id));
}

const SCREENS = {
  async dashboard(el) {
    el.innerHTML = `<h3>Dashboard</h3>`;
    try {
      const [health, metrics, events] = await Promise.all([
        api("GET", "/api/v1/health/"),
        api("GET", "/api/v1/metrics/"),
        api("GET", "/api/v1/events/status"),
      ]);
      el.innerHTML += `<pre>${esc(JSON.stringify({ health, metrics, events }, null, 2))}</pre>`;
    } catch (e) {}
  },
  async sources(el) {
    el.innerHTML = await _list("Sources", "/api/v1/sources/") +
      `<button onclick="createSource()">add</button>` +
      `<div id="src-form" style="display:none"></div>`;
  },
  async zones(el) {
    el.innerHTML = await _list("Zones", "/api/v1/zones/") +
      `<button onclick="createZone()">add</button>`;
  },
  async rules(el) {
    el.innerHTML = await _list("Rules", "/api/v1/rules/") +
      `<button onclick="createRule()">add</button>`;
  },
  async profiles(el) {
    el.innerHTML = await _list("Profiles", "/api/v1/profiles/") +
      `<button onclick="createProfile()">add</button>` +
      `<button onclick="activateProfile()">activate</button>`;
  },
  async sessions(el) {
    el.innerHTML = await _list("Sessions", "/api/v1/sessions/") +
      `<button onclick="startSession()">start</button>` +
      `<button onclick="stopSession()">stop</button>` +
      `<button onclick="sessionObservations()">observations</button>` +
      `<button onclick="sessionStream()">stream</button>` +
      `<pre id="sess-out"></pre>`;
  },
  async captures(el) {
    el.innerHTML = await _list("Captures", "/api/v1/captures/") +
      `<button onclick="captureSource()">capture source</button>`;
  },
  async artifacts(el) {
    el.innerHTML = await _list("Artifacts", "/api/v1/artifacts/") +
      `<button onclick="downloadArtifact()">download</button>`;
  },
  async pipelines(el) {
    el.innerHTML = await _list("Pipelines", "/api/v1/pipelines/") +
      `<button onclick="createPipeline()">add</button>` +
      `<button onclick="validatePipeline()">validate</button>`;
  },
  async analyze(el) {
    el.innerHTML = `<h3>Analyze</h3>
      <input id="an-src" placeholder="source_id or media_id">
      <input id="an-pipe" placeholder="pipeline_id (optional)">
      <button onclick="runAnalyze()">run</button>
      <button onclick="analyzeImage()">image file</button>
      <input id="an-file" type="file" accept="image/*">
      <pre id="an-out"></pre>`;
  },
  async view(el) {
    el.innerHTML = `<h3>View</h3>
      <input id="vw-src" placeholder="source_id">
      <button onclick="startView()">stream</button>
      <button onclick="stopStreams()">stop</button>
      <p><img id="vw-img" alt="live view"></p>`;
  },
  async monitors(el) {
    el.innerHTML = await _list("Monitors", "/api/v1/monitors/") +
      `<button onclick="createMonitor()">add</button>`;
  },
  async observations(el) {
    el.innerHTML = await _list("Observations", "/api/v1/observations/");
  },
  async media(el) {
    el.innerHTML = await _list("Media", "/api/v1/media/") +
      `<input id="md-file" type="file"><button onclick="uploadMedia()">upload</button>`;
  },
  async jobs(el) {
    el.innerHTML = await _list("Jobs", "/api/v1/jobs/");
  },
  async recordings(el) {
    el.innerHTML = await _list("Recordings", "/api/v1/recordings/");
  },
  async settings(el) {
    el.innerHTML = await _list("Settings", "/api/v1/settings/");
  },
  async config(el) {
    el.innerHTML = `<h3>Configuration</h3>
      <button onclick="exportCfg()">export</button>
      <button onclick="validateCfg()">validate</button>
      <button onclick="importCfg()">import</button>
      <pre id="cfg-out"></pre>`;
  },
  async ops(el) {
    el.innerHTML = `<h3>Operations</h3>
      <button onclick="showCaps()">capabilities</button>
      <button onclick="showMetrics()">metrics</button>
      <pre id="ops-out"></pre>`;
  },
};

/* Actions that map 1:1 to REST ops */
async function createSource() {
  const j = prompt("SourceCreate JSON:");
  if (j) { await mutate("POST", "/api/v1/sources/", JSON.parse(j)); render("sources"); }
}
async function createPipeline() {
  const j = prompt("PipelineCreate JSON:");
  if (j) { await mutate("POST", "/api/v1/pipelines/", JSON.parse(j)); render("pipelines"); }
}
async function validatePipeline() {
  const j = prompt("PipelineCreate JSON to validate:");
  if (j) { const r = await api("POST", "/api/v1/pipelines/validate", { body: JSON.parse(j) });
           toast(JSON.stringify(r)); }
}
async function createMonitor() {
  const j = prompt("MonitorCreate JSON:");
  if (j) { await mutate("POST", "/api/v1/monitors/", JSON.parse(j)); render("monitors"); }
}
async function createZone() {
  const j = prompt("ZoneCreate JSON:");
  if (j) { await mutate("POST", "/api/v1/zones/", JSON.parse(j)); render("zones"); }
}
async function createRule() {
  const j = prompt("RuleCreate JSON:");
  if (j) { await mutate("POST", "/api/v1/rules/", JSON.parse(j)); render("rules"); }
}
async function createProfile() {
  const j = prompt("ProfileCreate JSON:");
  if (j) { await mutate("POST", "/api/v1/profiles/", JSON.parse(j)); render("profiles"); }
}
async function activateProfile() {
  const id = prompt("Profile id to activate:");
  if (id) { await mutate("POST", `/api/v1/profiles/${id}/activate`); render("profiles"); }
}
async function startSession() {
  const j = prompt("SessionCreate JSON:", '{"source_id":"cam","pipeline_id":"p1"}');
  if (j) { await mutate("POST", "/api/v1/sessions/", JSON.parse(j)); render("sessions"); }
}
async function stopSession() {
  const id = prompt("Session id to stop:");
  if (id) { await api("POST", `/api/v1/sessions/${id}/stop`); render("sessions"); }
}
async function sessionObservations() {
  const id = prompt("Session id:");
  if (id) $("#sess-out").textContent =
    JSON.stringify(await api("GET", `/api/v1/sessions/${id}/observations/`), null, 2);
}
async function sessionStream() {
  const id = prompt("Session id:");
  if (!id) return;
  $("#sess-out").textContent = "";
  await stream(`/api/v1/sessions/${id}/stream`,
    ev => { $("#sess-out").textContent += ev + "\n\n"; });
}
async function captureSource() {
  const id = prompt("Source id:");
  if (id) { await mutate("POST", `/api/v1/sources/${id}/captures/`,
                          { retain: true }); render("captures"); }
}
async function downloadArtifact() {
  const id = prompt("Artifact id:");
  if (id) window.open(`/api/v1/artifacts/${id}/content`, "_blank");
}

async function runAnalyze() {
  const src = $("#an-src").value, pipe = $("#an-pipe").value;
  const body = { source: { source_id: src } };
  if (pipe) body.pipeline_id = pipe;
  const r = await api("POST", "/api/v1/analyze/", { body });
  $("#an-out").textContent = JSON.stringify(r, null, 2);
}
async function analyzeImage() {
  const f = $("#an-file").files[0]; if (!f) return toast("pick a file", true);
  const fd = new FormData(); fd.append("image", f);
  const resp = await fetch("/api/v1/analyze/image",
    { method: "POST", headers: _auth(), body: fd });
  $("#an-out").textContent = JSON.stringify(await resp.json(), null, 2);
}
async function startView() {
  const id = $("#vw-src").value; if (!id) return;
  stopStreams();
  const resp = await fetch(`/api/v1/sources/${id}/stream`, { headers: _auth() });
  if (!resp.ok) { await _raise(resp); return; }
  const rd = resp.body.getReader();
  const chunks = [];
  _abort = new AbortController();
  (async () => {
    try {
      while (true) {
        const { done, value } = await rd.read();
        if (done) break;
        chunks.push(value);
        if (chunks.length > 2) chunks.shift();
        const blob = new Blob(chunks, { type: "image/jpeg" });
        $("#vw-img").src = URL.createObjectURL(blob);
      }
    } catch {}
  })();
}
async function uploadMedia() {
  const f = $("#md-file").files[0]; if (!f) return toast("pick a file", true);
  const fd = new FormData(); fd.append("file", f);
  const resp = await fetch("/api/v1/media/", { method: "POST", headers: _auth(), body: fd });
  if (resp.ok) render("media"); else await _raise(resp);
}
async function exportCfg() {
  $("#cfg-out").textContent = JSON.stringify(await api("GET", "/api/v1/configuration/export"), null, 2);
}
async function validateCfg() {
  const j = prompt("PortableConfiguration JSON:");
  if (j) $("#cfg-out").textContent = JSON.stringify(
    await api("POST", "/api/v1/configuration/validate", { body: JSON.parse(j) }), null, 2);
}
async function importCfg() {
  const j = prompt("ConfigurationImport JSON:");
  if (j) $("#cfg-out").textContent = JSON.stringify(
    await mutate("POST", "/api/v1/configuration/import", JSON.parse(j)), null, 2);
}
async function showCaps() {
  $("#ops-out").textContent = JSON.stringify(await api("GET", "/api/v1/capabilities/"), null, 2);
}
async function showMetrics() {
  $("#ops-out").textContent = JSON.stringify(await api("GET", "/api/v1/metrics/"), null, 2);
}
const GROUPS = ["dashboard", "sources", "zones", "rules", "profiles",
                "sessions", "pipelines", "analyze", "view", "monitors",
                "observations", "media", "captures", "artifacts", "jobs",
                "recordings", "settings", "config", "ops"];
GROUPS.forEach(id => {
  const b = document.createElement("button");
  b.textContent = id; b.onclick = () => render(id);
  $("#nav").append(b);
});
$("#bearer").value = _bearer;
$("#bearer").addEventListener("change", e => {
  _bearer = e.target.value;
  sessionStorage.setItem("opal_token", _bearer);
});
render("dashboard").catch(() => {});

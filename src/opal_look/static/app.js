/* OPAL Look SPA (MVP v1.7.1) — thin REST client, no business logic. */
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
      const [health, info] = await Promise.all([
        api("GET", "/api/v1/health/"),
        api("GET", "/api/v1/info/"),
      ]);
      el.innerHTML += `<pre>${esc(JSON.stringify({ health, info }, null, 2))}</pre>`;
    } catch (e) {}
  },
  async streams(el) {
    el.innerHTML = await _list("Streams", "/api/v1/stream/") +
      `<input id="st-src" placeholder="rtsp://camera/live" size="40">
       <input id="st-eng" placeholder="engine_id (optional)">
       <input id="st-mod" placeholder="model_id (with engine)">
       <button onclick="startStream()">start</button>
       <button onclick="stopStream()">stop</button>
       <button onclick="streamEvents()">watch</button>
       <button onclick="streamVideo()">video</button>
       <button onclick="streamSnapshot()">snapshot</button>
       <button onclick="streamMetrics()">metrics</button>
       <pre id="st-out"></pre><p><img id="st-img" alt="live view"></p>`;
  },
  async predict(el) {
    el.innerHTML = `<h3>Predict</h3>
      <input id="pr-eng" placeholder="engine_id">
      <input id="pr-mod" placeholder="model_id">
      <input id="pr-src" placeholder="image path or URI" size="40">
      <input id="pr-conf" placeholder="confidence (0-1)">
      <button onclick="runPredict()">predict</button>
      <pre id="pr-out"></pre>`;
  },
  async models(el) {
    el.innerHTML = await _list("Models", "/api/v1/model/") +
      `<button onclick="loadModel()">load</button>` +
      `<button onclick="unloadModel()">unload</button>`;
  },
  async engines(el) {
    el.innerHTML = await _list("Engines", "/api/v1/engine/") +
      `<button onclick="discoverEngines()">discover</button>` +
      `<button onclick="engineCaps()">capabilities</button>`;
  },
  async hardware(el) {
    el.innerHTML = await _list("Hardware", "/api/v1/hardware/");
  },
  async profiles(el) {
    el.innerHTML = await _list("Profiles", "/api/v1/profile/") +
      `<button onclick="createProfile()">add</button>` +
      `<button onclick="activateProfile()">activate</button>`;
  },
  async settings(el) {
    el.innerHTML = await _list("Settings", "/api/v1/setting/");
  },
  async backup(el) {
    el.innerHTML = `<h3>Backup</h3>
      <button onclick="exportCfg()">export</button>
      <button onclick="validateCfg()">validate</button>
      <button onclick="importCfg()">import</button>
      <button onclick="createBackup()">create</button>
      <button onclick="listBackups()">list</button>
      <button onclick="downloadBackup()">download</button>
      <button onclick="restoreBackup()">restore</button>
      <button onclick="deleteBackup()">remove</button>
      <pre id="cfg-out"></pre>`;
  },
  async ops(el) {
    el.innerHTML = `<h3>Operations</h3>
      <button onclick="showInfo()">info</button>
      <button onclick="pingInfo()">ping</button>
      <button onclick="svcLog()">service log</button>
      <pre id="ops-out"></pre>`;
  },
};

/* Actions that map 1:1 to REST ops */
async function createProfile() {
  const j = prompt("ProfileCreate JSON:");
  if (j) { await mutate("POST", "/api/v1/profile/", JSON.parse(j)); render("profiles"); }
}
async function activateProfile() {
  const id = prompt("Profile id to activate:");
  if (id) { await mutate("POST", `/api/v1/profile/${id}/activate`); render("profiles"); }
}
async function discoverEngines() {
  toast(JSON.stringify(await api("POST", "/api/v1/engine/discover")));
  render("engines");
}
async function engineCaps() {
  const id = prompt("Engine id:");
  if (id) toast(JSON.stringify(await api("GET", `/api/v1/engine/${id}/capabilities`)));
}
async function loadModel() {
  const id = prompt("Model id:"); if (!id) return;
  const eng = prompt("Engine id (optional):");
  const q = eng ? `?engine_id=${encodeURIComponent(eng)}` : "";
  await api("POST", `/api/v1/model/${id}/load${q}`); render("models");
}
async function unloadModel() {
  const id = prompt("Model id:"); if (!id) return;
  const eng = prompt("Engine id (optional):");
  const q = eng ? `?engine_id=${encodeURIComponent(eng)}` : "";
  await api("POST", `/api/v1/model/${id}/unload${q}`); render("models");
}
async function runPredict() {
  const body = {
    engine_id: $("#pr-eng").value, model_id: $("#pr-mod").value,
    source: $("#pr-src").value,
  };
  const conf = parseFloat($("#pr-conf").value);
  if (!isNaN(conf)) body.confidence = conf;
  $("#pr-out").textContent = JSON.stringify(
    await api("POST", "/api/v1/predict", { body }), null, 2);
}
async function startStream() {
  const body = { source: $("#st-src").value };
  if ($("#st-eng").value) body.engine_id = $("#st-eng").value;
  if ($("#st-mod").value) body.model_id = $("#st-mod").value;
  const r = await api("POST", "/api/v1/stream/", { body });
  $("#st-out").textContent = JSON.stringify(r, null, 2);
}
async function stopStream() {
  const id = prompt("Stream id to stop:");
  if (id) { await api("POST", `/api/v1/stream/${id}/stop`); render("streams"); }
}
async function streamEvents() {
  const id = prompt("Stream id:"); if (!id) return;
  $("#st-out").textContent = "";
  await stream(`/api/v1/stream/${id}/events`,
    ev => { $("#st-out").textContent += ev + "\n\n"; });
}
async function streamVideo() {
  const id = prompt("Stream id:"); if (!id) return;
  stopStreams();
  const resp = await fetch(`/api/v1/stream/${id}/video`, { headers: _auth() });
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
        $("#st-img").src = URL.createObjectURL(blob);
      }
    } catch {}
  })();
}
async function streamSnapshot() {
  const id = prompt("Stream id:"); if (!id) return;
  window.open(`/api/v1/stream/${id}/snapshot`, "_blank");
}
async function streamMetrics() {
  const id = prompt("Stream id:"); if (!id) return;
  $("#st-out").textContent = JSON.stringify(
    await api("GET", `/api/v1/stream/${id}/metrics`), null, 2);
}
async function exportCfg() {
  $("#cfg-out").textContent = JSON.stringify(await api("GET", "/api/v1/backup/export"), null, 2);
}
async function validateCfg() {
  const j = prompt("OpalConfigExport JSON:");
  if (j) $("#cfg-out").textContent = JSON.stringify(
    await api("POST", "/api/v1/backup/validate", { body: JSON.parse(j) }), null, 2);
}
async function importCfg() {
  const j = prompt("OpalConfigExport JSON:");
  if (j) $("#cfg-out").textContent = JSON.stringify(
    await mutate("POST", "/api/v1/backup/import", JSON.parse(j)), null, 2);
}
async function createBackup() {
  $("#cfg-out").textContent = JSON.stringify(
    await api("POST", "/api/v1/backup/create"), null, 2);
}
async function listBackups() {
  $("#cfg-out").textContent = JSON.stringify(
    await api("GET", "/api/v1/backup/list"), null, 2);
}
async function downloadBackup() {
  const name = prompt("Backup filename:");
  if (name) window.open(`/api/v1/backup/download/${name}`, "_blank");
}
async function restoreBackup() {
  const name = prompt("Backup filename to restore:");
  if (name) $("#cfg-out").textContent = JSON.stringify(
    await mutate("POST", `/api/v1/backup/restore/${name}`), null, 2);
}
async function deleteBackup() {
  const name = prompt("Backup filename to remove:");
  if (name) { await api("DELETE", `/api/v1/backup/${name}`); render("backup"); }
}
async function showInfo() {
  $("#ops-out").textContent = JSON.stringify(await api("GET", "/api/v1/info/"), null, 2);
}
async function pingInfo() {
  $("#ops-out").textContent = JSON.stringify(await api("GET", "/api/v1/info/ping"), null, 2);
}
async function svcLog() {
  $("#ops-out").textContent = JSON.stringify(await api("GET", "/api/v1/service/log"), null, 2);
}
const GROUPS = ["dashboard", "streams", "predict", "models", "engines",
                "hardware", "profiles", "settings", "backup", "ops"];
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

/* OPAL Look SPA — thin REST client, no business logic. */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const sec = id => $(`#sec-${id}`);

function toast(msg, err = false) {
  const d = document.createElement("div");
  d.className = "toast" + (err ? " err" : "");
  d.textContent = msg;
  $("#toast").append(d);
  setTimeout(() => d.remove(), 6000);
}

async function api(method, path, { body, files, raw } = {}) {
  const opts = { method, headers: {} };
  if (files) opts.body = files;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  const etag = resp.headers.get("etag");
  if (etag) { const e = $("#etag"); e.textContent = `ETag ${etag.slice(0, 18)}…`; }
  if (raw) {
    if (!resp.ok) { await _raise(resp); }
    return resp;
  }
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    const err = data && data.error ? `${resp.status} ${data.error.code}: ${data.error.message}` : `${resp.status}`;
    toast(err, true); throw new Error(err);
  }
  return data;
}
async function _raise(resp) {
  let msg = `${resp.status}`;
  try { const d = await resp.json(); if (d.error) msg = `${resp.status} ${d.error.code}: ${d.error.message}`; } catch {}
  toast(msg, true); throw new Error(msg);
}

/* If-Match helpers: fetch collection ETag then mutate. */
async function mutate(method, path, body, etagOf = "/api/v1/settings/") {
  let etag = '"*"';
  try { const r = await fetch(etagOf); etag = r.headers.get("etag") || etag; } catch {}
  const resp = await fetch(path, {
    method,
    headers: { "If-Match": etag, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    const err = data && data.error ? `${resp.status} ${data.error.code}: ${data.error.message}` : `${resp.status}`;
    toast(err, true); throw new Error(err);
  }
  return data;
}

function jtry(text) { try { return JSON.parse(text); } catch { return undefined; } }

function table(cols, rows) {
  const t = document.createElement("table");
  t.innerHTML = `<thead><tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr></thead>`;
  const tb = document.createElement("tbody");
  for (const r of rows) tb.append(r);
  t.append(tb); return t;
}
function tr(cells) {
  const r = document.createElement("tr");
  for (const c of cells) {
    const td = document.createElement("td");
    if (typeof c === "string") td.textContent = c; else td.append(c);
    r.append(td);
  }
  return r;
}
function btn(label, fn, cls = "act") {
  const b = document.createElement("button");
  b.className = cls; b.textContent = label; b.onclick = fn; return b;
}
function field(label, name, value = "", type = "text") {
  return `<label>${label}<input name="${name}" value="${value}" type="${type}"></label>`;
}
function form(fields, submitLabel, onsubmit) {
  const f = document.createElement("form");
  f.className = "inline";
  f.innerHTML = fields + `<button class="act primary" type="submit">${submitLabel}</button>`;
  f.onsubmit = e => { e.preventDefault(); onsubmit(new FormData(f)); };
  return f;
}
function card(...children) {
  const d = document.createElement("div");
  d.className = "card"; d.append(...children); return d;
}
function jval(fd, name) {
  const v = fd.get(name);
  if (v === null || v === "") return undefined;
  const p = jtry(v); return p === undefined ? v : p;
}

/* ---------- sections ---------- */

const SECTIONS = [
  ["dashboard", "Dashboard"], ["engines", "Engines"], ["models", "Models"],
  ["sources", "Sources"], ["profiles", "Profiles"], ["media", "Media"],
  ["analyze", "Analyze"], ["sessions", "Sessions"], ["results", "Results"],
  ["snapshots", "Snapshots"], ["settings", "Settings"], ["backup", "Backup"],
];

async function renderDashboard() {
  const s = sec("dashboard"); s.innerHTML = "<h2>Dashboard</h2>";
  const [info, health] = await Promise.all([api("GET", "/"), api("GET", "/api/v1/health/")]);
  const pill = $("#health");
  pill.textContent = `health ${health.status} · ready=${health.ready}`;
  pill.className = "pill " + (health.ready ? "ok" : "err");
  s.append(
    card(Object.assign(document.createElement("h3"), {textContent: "Service"}),
         Object.assign(document.createElement("pre"), {textContent: JSON.stringify(info, null, 2)})),
    card(Object.assign(document.createElement("h3"), {textContent: "Health"}),
         Object.assign(document.createElement("pre"), {textContent: JSON.stringify(health, null, 2)})));
}

async function renderEngines() {
  const s = sec("engines"); s.innerHTML = "<h2>Engines</h2>";
  const rows = await api("GET", "/api/v1/engines/");
  s.append(table(["engine_id","name","execution","enabled","available","tasks",""],
    rows.map(e => tr([e.engine_id, e.name, e.execution, String(e.enabled), String(e.available),
      (e.capabilities.tasks || []).join(","),
      span(
        btn("toggle", async () => { await mutate("PATCH", `/api/v1/engines/${e.engine_id}`, {enabled: !e.enabled}); renderEngines(); }),
        btn("validate", async () => showJson(await api("POST", `/api/v1/engines/${e.engine_id}/validate`))),
      )]))));
}

async function renderModels() {
  const s = sec("models"); s.innerHTML = "<h2>Models</h2>";
  s.append(form(
    field("model_id","model_id") + field("name","name") +
    field("engine_id","engine_id","synthetic") + field("resource (json)","resource","{}"),
    "add", async fd => {
      const body = {model_id: fd.get("model_id"), name: fd.get("name"),
        engine_id: fd.get("engine_id"), resource: jval(fd, "resource") || {}};
      await mutate("POST", "/api/v1/models/", body, "/api/v1/models/"); renderModels();
    }));
  const rows = await api("GET", "/api/v1/models/");
  s.append(table(["model_id","name","engine","enabled","available","tasks",""],
    rows.map(m => tr([m.model_id, m.name, m.engine_id, String(m.enabled), String(m.available),
      (m.tasks||[]).join(","),
      span(
        btn("toggle", async () => { await mutate("PATCH", `/api/v1/models/${m.model_id}`, {enabled: !m.enabled}); renderModels(); }),
        btn("validate", async () => showJson(await api("POST", `/api/v1/models/${m.model_id}/validate`))),
        btn("delete", async () => { if(confirm(`delete ${m.model_id}?`)) { await mutate("DELETE", `/api/v1/models/${m.model_id}`); renderModels(); } }, "act danger"),
      )]))));
}

async function renderSources() {
  const s = sec("sources"); s.innerHTML = "<h2>Sources</h2>";
  s.append(form(
    field("source_id","source_id") + field("name","name") +
    `<label>type<select name="type">${["camera","rtsp","http","host_video","media"].map(t=>`<option>${t}</option>`).join("")}</select></label>` +
    field("locator","locator") + field("options (json)","source_options","{}"),
    "add", async fd => {
      const body = {source_id: fd.get("source_id"), name: fd.get("name"),
        type: fd.get("type"), locator: fd.get("locator"),
        source_options: jval(fd, "source_options") || {}};
      await mutate("POST", "/api/v1/sources/", body, "/api/v1/sources/"); renderSources();
    }));
  const rows = await api("GET", "/api/v1/sources/");
  s.append(table(["source_id","name","type","enabled","available","live","message",""],
    rows.map(x => tr([x.source_id, x.name, x.type, String(x.enabled), String(x.available),
      String(x.live), x.message || "",
      span(
        btn("toggle", async () => { await mutate("PATCH", `/api/v1/sources/${x.source_id}`, {enabled: !x.enabled}); renderSources(); }),
        btn("validate", async () => showJson(await api("POST", `/api/v1/sources/${x.source_id}/validate`))),
        btn("delete", async () => { if(confirm(`delete ${x.source_id}?`)) { await mutate("DELETE", `/api/v1/sources/${x.source_id}`); renderSources(); } }, "act danger"),
      )]))));
  const cams = await api("GET", "/api/v1/devices/cameras/");
  s.append(card(Object.assign(document.createElement("h3"),{textContent:"Discovered cameras"}),
    Object.assign(document.createElement("pre"),{textContent:JSON.stringify(cams,null,2)})));
}

async function renderProfiles() {
  const s = sec("profiles"); s.innerHTML = "<h2>Profiles</h2>";
  const models = await api("GET", "/api/v1/models/");
  s.append(form(
    field("name","name") +
    `<label>model<select name="model_id">${models.map(m=>`<option>${m.model_id}</option>`).join("")}</select></label>` +
    `<label>task<select name="task">${["detection","classification","segmentation","pose","ocr"].map(t=>`<option>${t}</option>`).join("")}</select></label>` +
    field("settings (json)","settings","{}"),
    "add", async fd => {
      await mutate("POST", "/api/v1/profiles/", {
        name: fd.get("name"), model_id: fd.get("model_id"), task: fd.get("task"),
        settings: jval(fd, "settings") || {}}, "/api/v1/profiles/");
      renderProfiles();
    }));
  const rows = await api("GET", "/api/v1/profiles/");
  s.append(table(["id","name","model","task","active",""],
    rows.map(p => tr([String(p.profile_id), p.name, p.model_id, p.task, String(p.active),
      span(
        btn("activate", async () => { await mutate("POST", `/api/v1/profiles/${p.profile_id}/activate`); renderProfiles(); }),
        btn("validate", async () => showJson(await api("POST", `/api/v1/profiles/${p.profile_id}/validate`))),
        btn("delete", async () => { if(confirm(`delete profile ${p.profile_id}?`)) { await mutate("DELETE", `/api/v1/profiles/${p.profile_id}`); renderProfiles(); } }, "act danger"),
      )]))));
}

async function renderMedia() {
  const s = sec("media"); s.innerHTML = "<h2>Media</h2>";
  const f = document.createElement("form"); f.className = "inline";
  f.innerHTML = `<label>file<input type="file" name="file" accept="image/jpeg,image/png"></label>
    <button class="act primary" type="submit">upload</button>`;
  f.onsubmit = async e => {
    e.preventDefault();
    const data = new FormData(f);
    const r = await api("POST", "/api/v1/media/", {files: data});
    toast(`uploaded ${r.media_id}`); renderMedia();
  };
  s.append(f);
  const page = await api("GET", "/api/v1/media/");
  s.append(table(["media_id","filename","kind","size","dims","expires","preview",""],
    page.items.map(m => tr([m.media_id, m.filename, m.kind, `${m.size_bytes}B`,
      `${m.width}×${m.height}`, m.expires_at,
      m.kind === "image" ? `<img class="preview" style="max-width:64px" src="/api/v1/media/${m.media_id}/content">` : "",
      span(btn("delete", async () => { await api("DELETE", `/api/v1/media/${m.media_id}`); renderMedia(); }, "act danger"))]))));
}

async function renderAnalyze() {
  const s = sec("analyze"); s.innerHTML = "<h2>Analyze</h2>";
  const [media, profiles, sources, models] = await Promise.all([
    api("GET", "/api/v1/media/"), api("GET", "/api/v1/profiles/"),
    api("GET", "/api/v1/sources/"), api("GET", "/api/v1/models/")]);
  const f = document.createElement("form"); f.className = "inline";
  f.innerHTML = `
    <label>input kind<select name="kind"><option>media</option><option>source</option></select></label>
    <label>media<select name="media_id">${media.items.map(m=>`<option>${m.media_id}</option>`).join("")}</select></label>
    <label>source<select name="source_id">${sources.map(x=>`<option>${x.source_id}</option>`).join("")}</select></label>
    <label>profile<select name="profile_id"><option value="">(none)</option>${profiles.map(p=>`<option value="${p.profile_id}">${p.name}</option>`).join("")}</select></label>
    <label>model<select name="model_id"><option value="">(auto)</option>${models.map(m=>`<option>${m.model_id}</option>`).join("")}</select></label>
    <label>task<select name="task"><option value="">(auto)</option>${["detection","classification","segmentation","pose","ocr"].map(t=>`<option>${t}</option>`).join("")}</select></label>
    <label>settings (json)<input name="settings" value="{}"></label>
    <button class="act primary" type="submit">analyze</button>`;
  const out = card(Object.assign(document.createElement("pre"), {textContent:"(no result)"}));
  f.onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(f);
    const input = fd.get("kind") === "media"
      ? {kind: "media", media_id: fd.get("media_id")}
      : {kind: "source", source_id: fd.get("source_id")};
    const body = {input};
    if (fd.get("profile_id")) body.profile_id = Number(fd.get("profile_id"));
    if (fd.get("model_id")) body.model_id = fd.get("model_id");
    if (fd.get("task")) body.task = fd.get("task");
    const settings = jval(fd, "settings"); if (settings && Object.keys(settings).length) body.settings = settings;
    const r = await api("POST", "/api/v1/analyze", {body});
    out.querySelector("pre").textContent = JSON.stringify(r, null, 2);
  };
  s.append(f, out);
}

async function renderSessions() {
  const s = sec("sessions"); s.innerHTML = "<h2>Sessions</h2>";
  const [sources, models] = await Promise.all([
    api("GET", "/api/v1/sources/"), api("GET", "/api/v1/models/")]);
  s.append(form(
    `<label>source<select name="source_id">${sources.map(x=>`<option>${x.source_id}</option>`).join("")}</select></label>` +
    `<label>model<select name="model_id"><option value="">(profile)</option>${models.map(m=>`<option>${m.model_id}</option>`).join("")}</select></label>` +
    `<label>task<select name="task"><option value="">(profile)</option>${["detection","classification","segmentation","pose","ocr"].map(t=>`<option>${t}</option>`).join("")}</select></label>`,
    "start", async fd => {
      const body = {source_id: fd.get("source_id")};
      if (fd.get("model_id")) body.model_id = fd.get("model_id");
      if (fd.get("task")) body.task = fd.get("task");
      await api("POST", "/api/v1/sessions/", {body});
      renderSessions();
    }));
  const page = await api("GET", "/api/v1/sessions/");
  s.append(table(["session_id","source","task","state","frames","last_result",""],
    page.items.map(x => tr([x.session_id, x.source_id, x.task, x.state,
      `${x.frames_analyzed}/${x.frames_dropped}`, x.last_result_id || "",
      span(
        btn("latest", async () => showJson(await api("GET", `/api/v1/sessions/${x.session_id}/results/latest`))),
        btn("events", () => streamEvents(x.session_id)),
        btn("preview", () => showPreview(x.session_id)),
        btn("stop", async () => { await api("POST", `/api/v1/sessions/${x.session_id}/stop`); renderSessions(); }),
        btn("delete", async () => { await api("DELETE", `/api/v1/sessions/${x.session_id}`); renderSessions(); }, "act danger"),
      )]))));
}

function streamEvents(sid) {
  const s = sec("sessions");
  const log = card(Object.assign(document.createElement("h3"),{textContent:`events ${sid}`}),
                   Object.assign(document.createElement("div"),{className:"log"}));
  s.append(log);
  const es = new EventSource(`/api/v1/sessions/${sid}/results/events`);
  es.onmessage = e => { log.querySelector(".log").textContent += e.data + "\n"; };
  es.addEventListener("result", e => { log.querySelector(".log").textContent += "result " + e.data.slice(0,300) + "\n"; });
  es.addEventListener("state", e => { log.querySelector(".log").textContent += "state " + e.data + "\n"; });
  es.addEventListener("end", () => { log.querySelector(".log").textContent += "— end —\n"; es.close(); });
  es.onerror = () => { es.close(); };
}

function showPreview(sid) {
  const s = sec("sessions");
  s.append(card(Object.assign(document.createElement("h3"),{textContent:`preview ${sid}`}),
    Object.assign(document.createElement("img"),{className:"preview",src:`/api/v1/sessions/${sid}/preview`})));
}

async function renderResults() {
  const s = sec("results"); s.innerHTML = "<h2>Results</h2>";
  const f = form(
    field("source_id","source_id") + field("model_id","model_id") +
    `<label>task<select name="task"><option value="">any</option>${["detection","classification","segmentation","pose","ocr"].map(t=>`<option>${t}</option>`).join("")}</select></label>` +
    field("class_label","class_label") + field("text","text"),
    "search", fd => renderResults({source_id: fd.get("source_id")||undefined,
      model_id: fd.get("model_id")||undefined, task: fd.get("task")||undefined,
      class_label: fd.get("class_label")||undefined, text: fd.get("text")||undefined}));
  s.append(f);
  const filters = arguments[0] || {};
  const qs = new URLSearchParams(Object.entries(filters).filter(([,v])=>v)).toString();
  const page = await api("GET", "/api/v1/results/" + (qs ? `?${qs}` : ""));
  s.append(table(["result_id","session","source","task","analyzed","objects",""],
    page.items.map(r => tr([r.result_id, r.session_id || "", r.source_id || r.media_id || "",
      r.task, r.analyzed_at,
      String((r.payload.objects||r.payload.classes||r.payload.instances||r.payload.poses||r.payload.regions||[]).length),
      span(
        btn("raw", () => showJson(r)),
        btn("snapshot", async () => { const j = await api("POST", `/api/v1/results/${r.result_id}/snapshot`, {body:{annotated:true,retain:true}}); toast(`snapshot ${j.snapshot_id}`); }),
        btn("delete", async () => { await api("DELETE", `/api/v1/results/${r.result_id}`); renderResults(); }, "act danger"),
      )]))));
}

async function renderSnapshots() {
  const s = sec("snapshots"); s.innerHTML = "<h2>Snapshots</h2>";
  const page = await api("GET", "/api/v1/snapshots/");
  s.append(table(["snapshot_id","result","annotated","created","expires","preview",""],
    page.items.map(x => tr([x.snapshot_id, x.result_id, String(x.annotated), x.created_at,
      x.expires_at,
      `<img class="preview" style="max-width:64px" src="/api/v1/snapshots/${x.snapshot_id}/content">`,
      span(btn("delete", async () => { await api("DELETE", `/api/v1/snapshots/${x.snapshot_id}`); renderSnapshots(); }, "act danger"))]))));
}

async function renderSettings() {
  const s = sec("settings"); s.innerHTML = "<h2>Settings</h2>";
  const settings = await api("GET", "/api/v1/settings/");
  s.append(table(["key","value",""], Object.entries(settings).map(([k,v]) =>
    tr([k, JSON.stringify(v),
      span(
        btn("edit", async () => {
          const nv = prompt(`${k}`, JSON.stringify(v));
          if (nv === null) return;
          await mutate("PUT", `/api/v1/settings/${k}`, {value: jtry(nv) ?? nv});
          renderSettings();
        }),
        btn("unset", async () => { await mutate("DELETE", `/api/v1/settings/${k}`); renderSettings(); }),
      )]))));
}

async function renderBackup() {
  const s = sec("backup"); s.innerHTML = "<h2>Backup</h2>";
  const actions = document.createElement("div");
  actions.className = "row";
  actions.append(
    btn("export → file", async () => {
      const data = await api("GET", "/api/v1/backup/export");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)],{type:"application/json"}));
      a.download = "opal-look-export.json"; a.click();
    }, "act primary"),
    btn("create", async () => { const r = await api("POST", "/api/v1/backup/create"); toast(`created ${r.filename}`); renderBackup(); }),
    btn("validate config", async () => showJson(await api("GET", "/api/v1/backup/validate"))),
  );
  const imp = document.createElement("form"); imp.className = "inline";
  imp.innerHTML = `<label>import file<input type="file" name="file" accept=".json"></label>
    <button class="act" type="submit">import</button>
    <button class="act" type="button" id="vonly">validate file</button>`;
  imp.onsubmit = async e => {
    e.preventDefault();
    const text = await imp.file.files[0].text();
    const r = await mutate("POST", "/api/v1/backup/import", JSON.parse(text));
    showJson(r); renderBackup();
  };
  imp.querySelector("#vonly").onclick = async () => {
    const text = await imp.file.files[0].text();
    showJson(await api("POST", "/api/v1/backup/validate", {body: JSON.parse(text)}));
  };
  s.append(card(actions), imp);
  const list = await api("GET", "/api/v1/backup/list");
  s.append(table(["filename","created","size",""],
    list.map(b => tr([b.filename, b.created_at, `${b.size_bytes}B`,
      span(
        btn("download", async () => {
          const data = await api("GET", `/api/v1/backup/download/${b.filename}`);
          const a = document.createElement("a");
          a.href = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));
          a.download = b.filename; a.click();
        }),
        btn("restore", async () => { if(confirm(`restore ${b.filename}?`)) { showJson(await mutate("POST", `/api/v1/backup/restore/${b.filename}`)); renderBackup(); } }),
        btn("delete", async () => { await api("DELETE", `/api/v1/backup/${b.filename}`); renderBackup(); }, "act danger"),
      )]))));
}

function showJson(obj) {
  const cur = $(".jsonview"); if (cur) cur.remove();
  const d = card(Object.assign(document.createElement("pre"),{className:"jsonview",textContent:JSON.stringify(obj,null,2)}));
  $("main").prepend(d);
}
function span(...kids) { const d = document.createElement("span"); d.append(...kids); return d; }

/* ---------- nav ---------- */

const RENDERERS = {
  dashboard: renderDashboard, engines: renderEngines, models: renderModels,
  sources: renderSources, profiles: renderProfiles, media: renderMedia,
  analyze: renderAnalyze, sessions: renderSessions, results: renderResults,
  snapshots: renderSnapshots, settings: renderSettings, backup: renderBackup,
};

function activate(id) {
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("active", b.dataset.sec === id));
  document.querySelectorAll("main section").forEach(x => x.classList.remove("on"));
  sec(id).classList.add("on");
  RENDERERS[id]().catch(e => console.error(e));
}

for (const [id, label] of SECTIONS) {
  const b = document.createElement("button");
  b.textContent = label; b.dataset.sec = id;
  b.onclick = () => activate(id);
  $("#nav").append(b);
}
activate("dashboard");

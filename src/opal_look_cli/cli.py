"""opal-look: thin REST client mirroring the v1.7.1 contract.

Group/verb layout follows the contract's x-opal-cli metadata: canonical
`opal look [parent] [group] <command>` spellings — `config` parents the
configuration resources (model/pipeline/profile/zone/rule/monitor/
setting/persona), `data` parents the runtime data resources
(job/observation/media/capture/artifact/recording), and `engine`,
`source`, `session`, `analyze`, `backup`, `service`, `info` sit at top
level. Contract aliases (`settings patch`, `settings reset`) dispatch to
the canonical `config setting` verbs. All logic lives server-side; this
client only issues HTTP calls and honestly surfaces streaming/bearer
limits. `service` falls back to local pidfile control when the API is
unreachable — a dead server cannot answer REST.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import httpx
import typer

from .client import ApiClient, unwrap

app = typer.Typer(
    help="OPAL Look v1.7.1 REST CLI (thin client; no business logic).",
    epilog=(
        "Examples:\n"
        "  opal-look info health\n"
        "  opal-look --json engine list\n"
        "  opal-look --url http://host:8000 source list\n"
        "  opal-look config model list\n"
        "  opal-look data job list\n"
        "  opal-look tree                    # print the full command tree"),
)

_state: dict = {"url": "http://127.0.0.1:8000", "json_out": False,
                "transport": None, "inner": None}


@app.callback()
def _opts(
    url: str = typer.Option("http://127.0.0.1:8000", "--url", help="Service base URL"),
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    _state["url"], _state["json_out"] = url, json_out


def _client() -> ApiClient:
    return ApiClient(_state["url"], transport=_state["transport"],
                     inner=_state.get("inner"))


def _emit(data) -> None:
    if data is None:
        return
    if _state["json_out"] or isinstance(data, (dict, list)):
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        typer.echo(data)


def _body(json_body: Optional[str], file: Optional[Path]) -> dict | None:
    if file:
        return json.loads(Path(file).read_text())
    if json_body:
        return json.loads(json_body)
    return None


def _query(**params) -> str:
    pairs = [(k, v) for k, v in params.items() if v is not None]
    return ("?" + "&".join(f"{k}={v}" for k, v in pairs)) if pairs else ""


def _crud(name: str, base: str, epilog: str | None = None) -> typer.Typer:
    sub = typer.Typer(help=name, epilog=epilog)

    @sub.command("list")
    def _list(limit: int = typer.Option(None, "--limit")):
        _emit(unwrap(_client().get(base + _query(limit=limit))))

    @sub.command("show")
    def _show(resource_id: str):
        _emit(unwrap(_client().get(f"{base}{resource_id}")))

    @sub.command("add")
    def _add(body: str = typer.Option(None, "--body"),
             file: Path = typer.Option(None, "--file")):
        _emit(unwrap(_client().mutate("POST", base, json=_body(body, file))))

    @sub.command("update")
    def _update(resource_id: str, body: str = typer.Option(None, "--body"),
                file: Path = typer.Option(None, "--file")):
        _emit(unwrap(_client().mutate("PATCH", f"{base}{resource_id}",
                                      etag_path=f"{base}{resource_id}",
                                      json=_body(body, file))))

    @sub.command("remove")
    def _remove(resource_id: str):
        _emit(unwrap(_client().mutate("DELETE", f"{base}{resource_id}",
                                      etag_path=f"{base}{resource_id}")))
    return sub


def _stream_get(path: str, out: Path | None, limit_bytes: int,
                sse: bool = False) -> None:
    """Streamed GET: write SSE lines or raw bytes progressively — never
    buffers the whole stream."""
    with _client().stream("GET", path) as resp:
        if resp.status_code >= 400:
            resp.read()
            raise SystemExit(unwrap(resp))
        if sse:
            for line in resp.iter_lines():
                typer.echo(line)
        else:
            target = Path(out or "stream.mjpeg")
            written = 0
            with target.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
                    written += len(chunk)
                    if limit_bytes and written >= limit_bytes:
                        break
            typer.echo(str(target))


def _post_action(path: str, json_data=None) -> None:
    _emit(unwrap(_client().request("POST", path, json=json_data)))


# -- engine (installed adapters: list/show/update only) ------------------------

engine = typer.Typer(help="engine", epilog=(
    "Examples:\n"
    "  opal-look engine list\n"
    "  opal-look engine show synthetic"))


@engine.command("list")
def _engine_list():
    _emit(unwrap(_client().get("/api/v1/engine/")))


@engine.command("show")
def _engine_show(engine_id: str):
    _emit(unwrap(_client().get(f"/api/v1/engine/{engine_id}")))


@engine.command("update")
def _engine_update(engine_id: str, body: str = typer.Option(None, "--body"),
                   file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().mutate(
        "PATCH", f"/api/v1/engine/{engine_id}",
        etag_path=f"/api/v1/engine/{engine_id}", json=_body(body, file))))


app.add_typer(engine, name="engine")

# -- source ---------------------------------------------------------------------

src = _crud("source", "/api/v1/source/", epilog=(
    "Examples:\n"
    "  opal-look source add --file camera.json\n"
    "  opal-look source status SOURCE_ID\n"
    "  opal-look source probe SOURCE_ID\n"
    "  opal-look source frame SOURCE_ID --out frame.jpg\n"
    "  opal-look source stream SOURCE_ID --out clip.mjpeg\n"
    "  opal-look source capture SOURCE_ID --annotate"))


@src.command("status")
def _src_status(source_id: str):
    _emit(unwrap(_client().get(f"/api/v1/source/{source_id}/status")))


@src.command("probe")
def _src_probe(source_id: str):
    _post_action(f"/api/v1/source/{source_id}/probe")


@src.command("frame")
def _src_frame(source_id: str, out: Path = typer.Option(Path("frame.jpg"), "--out")):
    data = unwrap(_client().get(f"/api/v1/source/{source_id}/frame"))
    Path(out).write_bytes(data)
    typer.echo(str(out))


@src.command("stream")
def _src_stream(source_id: str, out: Path = typer.Option(None, "--out"),
                max_bytes: int = typer.Option(5_000_000, "--max-bytes"),
                pipeline_id: str = typer.Option(None, "--pipeline")):
    q = f"?pipeline_id={pipeline_id}" if pipeline_id else ""
    _stream_get(f"/api/v1/source/{source_id}/stream{q}", out, max_bytes)


@src.command("capture")
def _src_capture(source_id: str,
                 retain: bool = typer.Option(True, "--retain/--no-retain"),
                 annotate: bool = typer.Option(False, "--annotate"),
                 session_id: str = typer.Option(None, "--session"),
                 observation_id: str = typer.Option(None, "--observation")):
    body: dict = {"retain": retain}
    if annotate:
        body["annotate"] = True
    if session_id:
        body["session_id"] = session_id
    if observation_id:
        body["observation_id"] = observation_id
    _emit(unwrap(_client().mutate(
        "POST", f"/api/v1/source/{source_id}/capture/", json=body)))


app.add_typer(src, name="source")

# -- session --------------------------------------------------------------------

session = typer.Typer(help="session", epilog=(
    "Examples:\n"
    "  opal-look session start --body "
    "'{\"source_id\":\"cam\",\"pipeline_id\":\"p1\"}'\n"
    "  opal-look session list\n"
    "  opal-look session preview SESSION_ID --out view.mjpeg"))


@session.command("start")
def _sess_start(body: str = typer.Option(None, "--body"),
                file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().mutate("POST", "/api/v1/session/",
                                  json=_body(body, file))))


@session.command("list")
def _sess_list(state: str = typer.Option(None, "--state"),
               source_id: str = typer.Option(None, "--source"),
               limit: int = typer.Option(None, "--limit")):
    _emit(unwrap(_client().get("/api/v1/session/" + _query(
        state=state, source_id=source_id, limit=limit))))


@session.command("show")
def _sess_show(session_id: str):
    _emit(unwrap(_client().get(f"/api/v1/session/{session_id}")))


@session.command("stop")
def _sess_stop(session_id: str):
    _emit(unwrap(_client().request(
        "POST", f"/api/v1/session/{session_id}/stop")))


@session.command("stream")
def _sess_stream(session_id: str):
    _stream_get(f"/api/v1/session/{session_id}/stream", None, 0, sse=True)


@session.command("preview")
def _sess_preview(session_id: str,
                  out: Path = typer.Option(None, "--out"),
                  max_bytes: int = typer.Option(5_000_000, "--max-bytes")):
    _stream_get(f"/api/v1/session/{session_id}/preview", out, max_bytes)


app.add_typer(session, name="session")

# -- analyze --------------------------------------------------------------------

analyze = typer.Typer(help="analyze", epilog=(
    "Examples:\n"
    "  opal-look analyze run --body "
    "'{\"source\":{\"source_id\":\"cam\"},\"pipeline_id\":\"p1\"}'\n"
    "  opal-look analyze image photo.jpg --request '{\"task\":\"detection\"}'"))


@analyze.command("run")
def _analyze_run(body: str = typer.Option(None, "--body"),
                 file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().request("POST", "/api/v1/analyze/",
                                   json=_body(body, file))))


@analyze.command("image")
def _analyze_image(file: Path,
                   request: str = typer.Option(None, "--request")):
    with open(file, "rb") as fh:
        parts = {"image": (file.name, fh)}
        if request:
            parts["request"] = (None, request)
        _emit(unwrap(_client().request("POST", "/api/v1/analyze/image",
                                       files=parts)))


app.add_typer(analyze, name="analyze")

# -- info -----------------------------------------------------------------------

info = typer.Typer(help="info", epilog=(
    "Examples:\n"
    "  opal-look info health\n"
    "  opal-look info version\n"
    "  opal-look info ping\n"
    "  opal-look info metrics"))

info.command("health")(lambda: _emit(unwrap(_client().get("/api/v1/health/"))))
info.command("live")(lambda: _emit(unwrap(_client().get("/api/v1/health/live"))))
info.command("ready")(lambda: _emit(unwrap(_client().get("/api/v1/health/ready"))))
info.command("version")(lambda: _emit(unwrap(_client().get("/api/v1/info/"))))
info.command("ping")(lambda: _emit(unwrap(_client().get("/api/v1/info/ping"))))
info.command("capabilities")(
    lambda: _emit(unwrap(_client().get("/api/v1/capabilities/"))))
info.command("metrics")(lambda: _emit(unwrap(_client().get("/api/v1/metrics/"))))
info.command("events")(
    lambda: _emit(unwrap(_client().get("/api/v1/events/status"))))
app.add_typer(info, name="info")

# -- backup ---------------------------------------------------------------------

backup = typer.Typer(help="backup", epilog=(
    "Examples:\n"
    "  opal-look backup export\n"
    "  opal-look backup validate --file bundle.json\n"
    "  opal-look backup import --file bundle.json\n"
    "  opal-look backup create\n"
    "  opal-look backup download opal-look-20260101T000000Z.json\n"
    "  opal-look backup restore opal-look-20260101T000000Z.json"))


@backup.command("list")
def _backup_list():
    _emit(unwrap(_client().get("/api/v1/backup/list")))


@backup.command("create")
def _backup_create():
    _emit(unwrap(_client().request("POST", "/api/v1/backup/create")))


@backup.command("download")
def _backup_download(
        filename: str,
        out: Path = typer.Option(None, "--out")):
    data = unwrap(_client().get(f"/api/v1/backup/download/{filename}"))
    target = Path(out or filename)
    target.write_bytes(data)
    typer.echo(str(target))


@backup.command("restore")
def _backup_restore(filename: str):
    _emit(unwrap(_client().mutate(
        "POST", f"/api/v1/backup/restore/{filename}")))


@backup.command("remove")
def _backup_remove(filename: str):
    _emit(unwrap(_client().request(
        "DELETE", f"/api/v1/backup/{filename}")))


@backup.command("export")
def _backup_export():
    _emit(unwrap(_client().get("/api/v1/backup/export")))


@backup.command("import")
def _backup_import(file: Path = typer.Option(None, "--file"),
                   body: str = typer.Option(None, "--body"),
                   bindings: Path = typer.Option(None, "--bindings")):
    """--file/--body supply the OpalConfigExport bundle; omitting both sends
    a null body (import the provisioned ./config/ file set)."""
    payload = _body(body, file)
    if payload is not None or bindings:
        payload = {"configuration": payload or {}}
        if bindings:
            payload["source_bindings"] = json.loads(
                Path(bindings).read_text())
    _emit(unwrap(_client().mutate("POST", "/api/v1/backup/import",
                                  json=payload)))


@backup.command("validate")
def _backup_validate(body: str = typer.Option(None, "--body"),
                     file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().request("POST", "/api/v1/backup/validate",
                                   json=_body(body, file))))


app.add_typer(backup, name="backup")

# -- service (REST first; local pidfile fallback when unreachable) --------------

service = typer.Typer(help="service", epilog=(
    "Examples:\n"
    "  opal-look service start\n"
    "  opal-look service stop\n"
    "  opal-look service log --lines 20\n"
    "\n"
    "Calls the REST /service/ ops when the API answers; falls back to the\n"
    "local pidfile/logs when the server is unreachable (e.g. cold start)."))


def _try_rest(fn):
    """REST call; None when the server cannot be reached at all."""
    try:
        return fn()
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return None


def _service_control():
    from opal_look import service_control
    return service_control


@service.command("start")
def _svc_start(
        append: bool = typer.Option(False, "--append",
                                    help="Append to the service log."),
        port: int = typer.Option(None, "--port"),
        host: str = typer.Option(None, "--host"),
        data_dir: str = typer.Option(None, "--data-dir")):
    """Start the managed server (restart when one is already running)."""
    resp = _try_rest(lambda: _client().request(
        "POST", "/api/v1/service/start", json={"append": append}))
    if resp is not None:
        _emit(unwrap(resp))
        return
    # Local fallback: the server is down — spawn it directly.
    sc = _service_control()
    env_extra = {}
    if port is not None:
        env_extra["OPAL_LOOK_PORT"] = str(port)
    if host is not None:
        env_extra["OPAL_LOOK_HOST"] = host
    if data_dir is not None:
        env_extra["OPAL_LOOK_DATA_DIR"] = data_dir
    managed = sc.read_pid()
    if managed is not None and sc.pid_alive(managed):
        sc.kill_pid(managed)
        typer.echo(f"killed running server (pid {managed})")
    sc.pid_path().unlink(missing_ok=True)
    pid = sc.spawn_server(append=append, wait_pid=managed,
                          env_extra=env_extra or None)
    typer.echo(f"started opal-look (pid {pid}); output -> {sc.log_path()}")


@service.command("stop")
def _svc_stop():
    """Stop the managed server; not an error when none is running."""
    resp = _try_rest(lambda: _client().request("POST", "/api/v1/service/stop"))
    if resp is not None:
        _emit(unwrap(resp))
        return
    sc = _service_control()
    pid = sc.read_pid()
    if pid is None or not sc.pid_alive(pid):
        sc.pid_path().unlink(missing_ok=True)
        typer.echo("no server running")
        return
    sc.kill_pid(pid)
    sc.pid_path().unlink(missing_ok=True)
    typer.echo(f"stopped opal-look (pid {pid})")


@service.command("log")
def _svc_log(lines: int = typer.Option(10, "--lines")):
    """Tail the service log (default 10 lines)."""
    resp = _try_rest(lambda: _client().get(
        "/api/v1/service/log", params={"lines": lines}))
    if resp is not None:
        data = unwrap(resp)
        if _state["json_out"]:
            _emit(data)
        else:
            for line in data.get("lines", []):
                typer.echo(line)
        return
    sc = _service_control()
    tail = sc.tail_log(lines)
    if tail is None:
        raise SystemExit(f"no log file at {sc.log_path()}")
    for line in tail:
        typer.echo(line)


app.add_typer(service, name="service")

# -- config parent group --------------------------------------------------------

config = typer.Typer(help="config", epilog=(
    "Examples:\n"
    "  opal-look config model list\n"
    "  opal-look config pipeline add --file pipeline.json\n"
    "  opal-look config setting list\n"
    "  opal-look config persona add --body '{\"persona_id\":\"amy\",\"name\":\"Amy\"}'"))

config.add_typer(_crud("model", "/api/v1/model/"), name="model")

_pipes = _crud("pipeline", "/api/v1/pipeline/", epilog=(
    "Examples:\n"
    "  opal-look config pipeline validate --file pipeline.json"))


@_pipes.command("validate")
def _pipe_validate(body: str = typer.Option(None, "--body"),
                   file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().request("POST", "/api/v1/pipeline/validate",
                                   json=_body(body, file))))


config.add_typer(_pipes, name="pipeline")

_profs = _crud("profile", "/api/v1/profile/")


@_profs.command("activate")
def _prof_activate(profile_id: str):
    _emit(unwrap(_client().mutate(
        "POST", f"/api/v1/profile/{profile_id}/activate")))


config.add_typer(_profs, name="profile")
config.add_typer(_crud("zone", "/api/v1/zone/"), name="zone")
config.add_typer(_crud("rule", "/api/v1/rule/"), name="rule")
config.add_typer(_crud("monitor", "/api/v1/monitor/"), name="monitor")

setting = typer.Typer(help="setting", epilog=(
    "Examples:\n"
    "  opal-look config setting list\n"
    "  opal-look config setting update --body '{\"max_viewers\": 4}'\n"
    "  opal-look config setting set max_viewers 4\n"
    "  opal-look config setting remove max_viewers"))


@setting.command("list")
def _setting_list():
    _emit(unwrap(_client().get("/api/v1/setting/")))


@setting.command("show")
def _setting_show(key: str):
    _emit(unwrap(_client().get(f"/api/v1/setting/{key}")))


@setting.command("update")
def _setting_update(body: str = typer.Option(None, "--body"),
                    file: Path = typer.Option(None, "--file")):
    """Atomic whole-map PATCH of the settings map."""
    _emit(unwrap(_client().mutate("PATCH", "/api/v1/setting/",
                                  json=_body(body, file))))


@setting.command("set")
def _setting_set(key: str, value: str):
    _emit(unwrap(_client().mutate("PUT", f"/api/v1/setting/{key}",
                                  json={"value": json.loads(value)})))


@setting.command("remove")
def _setting_remove(key: str):
    _emit(unwrap(_client().mutate("DELETE", f"/api/v1/setting/{key}")))


config.add_typer(setting, name="setting")

persona = typer.Typer(help="persona", epilog=(
    "Examples:\n"
    "  opal-look config persona list\n"
    "  opal-look config persona add --body '{\"persona_id\":\"amy\",\"name\":\"Amy\"}'\n"
    "  opal-look config persona update amy --body '{\"voice_id\":\"en-gb-alan-low\"}'\n"
    "  opal-look config persona validate amy"))


@persona.command("list")
def _per_list(enabled: bool = typer.Option(None, "--enabled/--disabled")):
    q = "" if enabled is None else f"?enabled={'true' if enabled else 'false'}"
    _emit(unwrap(_client().get(f"/api/v1/persona/{q}")))


@persona.command("add")
def _per_add(body: str = typer.Option(None, "--body"),
             file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().mutate("POST", "/api/v1/persona/",
                                  json=_body(body, file))))


@persona.command("show")
def _per_show(persona_id: str):
    _emit(unwrap(_client().get(f"/api/v1/persona/{persona_id}")))


@persona.command("update")
def _per_update(persona_id: str,
                body: str = typer.Option(None, "--body"),
                file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().mutate(
        "PATCH", f"/api/v1/persona/{persona_id}",
        etag_path=f"/api/v1/persona/{persona_id}", json=_body(body, file))))


@persona.command("remove")
def _per_remove(persona_id: str):
    _emit(unwrap(_client().mutate(
        "DELETE", f"/api/v1/persona/{persona_id}",
        etag_path=f"/api/v1/persona/{persona_id}")))


@persona.command("validate")
def _per_validate(persona_id: str):
    _emit(unwrap(_client().request(
        "POST", f"/api/v1/persona/{persona_id}/validate")))


config.add_typer(persona, name="persona")
app.add_typer(config, name="config")

# -- data parent group ----------------------------------------------------------

data = typer.Typer(help="data", epilog=(
    "Examples:\n"
    "  opal-look data job submit --file job.json --idempotency-key run-001\n"
    "  opal-look data observation list --source cam\n"
    "  opal-look data capture download CAPTURE_ID --out cap.jpg"))

job = typer.Typer(help="job")


@job.command("submit")
def _job_submit(body: str = typer.Option(None, "--body"),
                file: Path = typer.Option(None, "--file"),
                idempotency_key: str = typer.Option(None, "--idempotency-key")):
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    _emit(unwrap(_client().request("POST", "/api/v1/job/",
                                   json=_body(body, file), headers=headers)))


@job.command("list")
def _job_list(state: str = typer.Option(None, "--state"),
              kind: str = typer.Option(None, "--kind"),
              limit: int = typer.Option(None, "--limit")):
    _emit(unwrap(_client().get("/api/v1/job/" + _query(
        state=state, kind=kind, limit=limit))))


@job.command("show")
def _job_show(job_id: str):
    _emit(unwrap(_client().get(f"/api/v1/job/{job_id}")))


@job.command("cancel")
def _job_cancel(job_id: str):
    _post_action(f"/api/v1/job/{job_id}/cancel")


data.add_typer(job, name="job")

observation = typer.Typer(help="observation")


@observation.command("list")
def _obs_list(source_id: str = typer.Option(None, "--source"),
              session_id: str = typer.Option(None, "--session"),
              job_id: str = typer.Option(None, "--job"),
              task: str = typer.Option(None, "--task"),
              label: str = typer.Option(None, "--label"),
              after: str = typer.Option(None, "--after"),
              before: str = typer.Option(None, "--before"),
              limit: int = typer.Option(None, "--limit")):
    _emit(unwrap(_client().get("/api/v1/observation/" + _query(
        source_id=source_id, session_id=session_id, job_id=job_id,
        task=task, label=label, after=after, before=before, limit=limit))))


@observation.command("show")
def _obs_show(observation_id: str):
    _emit(unwrap(_client().get(f"/api/v1/observation/{observation_id}")))


data.add_typer(observation, name="observation")

med = typer.Typer(help="media", epilog=(
    "Examples:\n"
    "  opal-look data media upload frame.jpg --ttl 3600\n"
    "  opal-look data media list"))


@med.command("upload")
def _media_upload(file: Path, ttl_seconds: int = typer.Option(None, "--ttl")):
    payload = {"ttl_seconds": ttl_seconds} if ttl_seconds else None
    with open(file, "rb") as fh:
        _emit(unwrap(_client().request("POST", "/api/v1/media/",
                                       files={"file": (file.name, fh)},
                                       data=payload)))


@med.command("list")
def _media_list(kind: str = typer.Option(None, "--kind"),
                source_id: str = typer.Option(None, "--source"),
                limit: int = typer.Option(None, "--limit")):
    _emit(unwrap(_client().get("/api/v1/media/" + _query(
        kind=kind, source_id=source_id, limit=limit))))


@med.command("show")
def _media_show(media_id: str):
    _emit(unwrap(_client().get(f"/api/v1/media/{media_id}")))


@med.command("remove")
def _media_remove(media_id: str):
    _emit(unwrap(_client().mutate("DELETE", f"/api/v1/media/{media_id}")))


data.add_typer(med, name="media")

capture = typer.Typer(help="capture", epilog=(
    "Examples:\n"
    "  opal-look data capture list\n"
    "  opal-look data capture download CAPTURE_ID --out cap.jpg"))


@capture.command("list")
def _cap_list(source_id: str = typer.Option(None, "--source"),
              limit: int = typer.Option(None, "--limit")):
    _emit(unwrap(_client().get("/api/v1/capture/" + _query(
        source_id=source_id, limit=limit))))


@capture.command("show")
def _cap_show(capture_id: str):
    _emit(unwrap(_client().get(f"/api/v1/capture/{capture_id}")))


@capture.command("remove")
def _cap_remove(capture_id: str):
    _emit(unwrap(_client().mutate(
        "DELETE", f"/api/v1/capture/{capture_id}")))


@capture.command("download")
def _cap_download(capture_id: str,
                  out: Path = typer.Option(Path("capture.jpg"), "--out")):
    resp = unwrap(_client().request(
        "GET", f"/api/v1/capture/{capture_id}/content"))
    Path(out).write_bytes(resp)
    typer.echo(str(out))


data.add_typer(capture, name="capture")

artifact = typer.Typer(help="artifact", epilog=(
    "Examples:\n"
    "  opal-look data artifact list\n"
    "  opal-look data artifact download ARTIFACT_ID --out video.mjpeg"))


@artifact.command("list")
def _art_list(kind: str = typer.Option(None, "--kind"),
              source_id: str = typer.Option(None, "--source"),
              job_id: str = typer.Option(None, "--job"),
              limit: int = typer.Option(None, "--limit")):
    _emit(unwrap(_client().get("/api/v1/artifact/" + _query(
        kind=kind, source_id=source_id, job_id=job_id, limit=limit))))


@artifact.command("show")
def _art_show(artifact_id: str):
    _emit(unwrap(_client().get(f"/api/v1/artifact/{artifact_id}")))


@artifact.command("remove")
def _art_remove(artifact_id: str):
    _emit(unwrap(_client().request(
        "DELETE", f"/api/v1/artifact/{artifact_id}")))


@artifact.command("download")
def _art_download(artifact_id: str,
                  out: Path = typer.Option(Path("artifact.bin"), "--out")):
    resp = unwrap(_client().request(
        "GET", f"/api/v1/artifact/{artifact_id}/content"))
    Path(out).write_bytes(resp)
    typer.echo(str(out))


data.add_typer(artifact, name="artifact")

rec = typer.Typer(help="recording", epilog=(
    "Examples:\n"
    "  opal-look data recording start --source SOURCE_ID --duration 30\n"
    "  opal-look data recording stop RECORDING_ID\n"
    "  opal-look data recording list"))


@rec.command("start")
def _rec_start(source_id: str = typer.Option(..., "--source"),
               pipeline_id: str = typer.Option(None, "--pipeline"),
               max_duration_seconds: int = typer.Option(None, "--duration")):
    body = {"source_id": source_id}
    if pipeline_id:
        body["pipeline_id"] = pipeline_id
    if max_duration_seconds:
        body["max_duration_seconds"] = max_duration_seconds
    _emit(unwrap(_client().mutate("POST", "/api/v1/recording/", json=body)))


@rec.command("list")
def _rec_list(limit: int = typer.Option(None, "--limit")):
    _emit(unwrap(_client().get("/api/v1/recording/" + _query(limit=limit))))


@rec.command("show")
def _rec_show(recording_id: str):
    _emit(unwrap(_client().get(f"/api/v1/recording/{recording_id}")))


@rec.command("stop")
def _rec_stop(recording_id: str):
    _emit(unwrap(_client().request(
        "POST", f"/api/v1/recording/{recording_id}/stop")))


data.add_typer(rec, name="recording")
app.add_typer(data, name="data")

# -- contract aliases -------------------------------------------------------------
# x-opal-cli aliases are alternate complete spellings for canonical ops.

settings = typer.Typer(help="settings", epilog=(
    "Alias spellings kept per contract x-opal-cli metadata; canonical "
    "verbs live under 'config setting'."))


@settings.command("patch", deprecated="use 'config setting update'")
def _settings_patch_alias(body: str = typer.Option(None, "--body"),
                          file: Path = typer.Option(None, "--file")):
    """Alias for 'config setting update' (PATCH the settings map)."""
    _setting_update(body, file)


@settings.command("reset", deprecated="use 'config setting remove'")
def _settings_reset_alias(key: str):
    """Alias for 'config setting remove' (DELETE one setting key)."""
    _setting_remove(key)


app.add_typer(settings, name="settings")

# -- extras (non-contract conveniences) -------------------------------------------

output = typer.Typer(help="common output retrieval", epilog=(
    "Examples:\n"
    "  opal-look output fetch /api/v1/capture/cap-0123/content --out frame.jpg\n"
    "  opal-look output fetch /api/v1/artifact/art-abc/content --out clip.mjpeg\n"
    "\n"
    "The content_url comes from `output_ref` (captures), `artifact_ref`\n"
    "(recordings) or `output_refs` (jobs) in show/list output."))


@output.command("fetch")
def _output_fetch(content_url: str,
                  out: Path = typer.Option(Path("output.bin"), "--out")):
    """Download output bytes from an output_ref content_url."""
    if not (content_url.startswith("/api/v1/capture/")
            or content_url.startswith("/api/v1/artifact/")) \
            or not content_url.endswith("/content"):
        raise SystemExit(
            "expected a content_url like /api/v1/capture/<id>/content "
            "or /api/v1/artifact/<id>/content")
    resp = unwrap(_client().request("GET", content_url))
    Path(out).write_bytes(resp)
    typer.echo(str(out))


app.add_typer(output, name="output")


from .tree_cmds import register as _register_tree

_register_tree(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

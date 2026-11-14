"""opal-look: thin REST client mirroring the MVP v1.7.1 contract.

Group/verb layout follows the contract's x-opal-cli metadata: canonical
`opal look [parent] [group] <command>` spellings — top-level groups are
`engine`, `model`, `predict`, `hardware`, `stream`, `backup`, `service`
and `info`; `config` parents `engine update`, `profile` and `setting`.
All logic lives server-side; this client only issues HTTP calls and
honestly surfaces streaming/bearer limits. `service` falls back to local
pidfile control when the API is unreachable — a dead server cannot
answer REST.
"""

from __future__ import annotations

import json
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
        "  opal-look engine list\n"
        "  opal-look predict image --engine synthetic --model m --source img.jpg\n"
        "  opal-look stream start rtsp://cam.local/live\n"
        "  opal-look stream watch-video STREAM_ID --out view.mjpeg\n"
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


# -- engine ----------------------------------------------------------------------

engine = typer.Typer(help="engine", epilog=(
    "Examples:\n"
    "  opal-look engine list\n"
    "  opal-look engine discover\n"
    "  opal-look engine capabilities synthetic"))


@engine.command("list")
def _engine_list():
    _emit(unwrap(_client().get("/api/v1/engine/")))


@engine.command("show")
def _engine_show(engine_id: str):
    _emit(unwrap(_client().get(f"/api/v1/engine/{engine_id}")))


@engine.command("discover")
def _engine_discover():
    _emit(unwrap(_client().request("POST", "/api/v1/engine/discover")))


@engine.command("capabilities")
def _engine_capabilities(engine_id: str):
    _emit(unwrap(_client().get(f"/api/v1/engine/{engine_id}/capabilities")))


app.add_typer(engine, name="engine")

# -- model -----------------------------------------------------------------------

model = typer.Typer(help="model", epilog=(
    "Examples:\n"
    "  opal-look model list\n"
    "  opal-look model show yolov8n --engine yolo\n"
    "  opal-look model load yolov8n --engine yolo"))


@model.command("list")
def _model_list(engine_id: str = typer.Option(None, "--engine")):
    _emit(unwrap(_client().get("/api/v1/model/" + _query(engine_id=engine_id))))


@model.command("show")
def _model_show(model_id: str,
                engine_id: str = typer.Option(None, "--engine")):
    _emit(unwrap(_client().get(
        f"/api/v1/model/{model_id}" + _query(engine_id=engine_id))))


@model.command("load")
def _model_load(model_id: str,
                engine_id: str = typer.Option(None, "--engine")):
    _emit(unwrap(_client().request(
        "POST", f"/api/v1/model/{model_id}/load" + _query(engine_id=engine_id))))


@model.command("unload")
def _model_unload(model_id: str,
                  engine_id: str = typer.Option(None, "--engine")):
    _emit(unwrap(_client().request(
        "POST", f"/api/v1/model/{model_id}/unload" + _query(engine_id=engine_id))))


app.add_typer(model, name="model")

# -- predict ---------------------------------------------------------------------

predict = typer.Typer(help="predict", epilog=(
    "Examples:\n"
    "  opal-look predict image --engine synthetic --model m --source img.jpg\n"
    "  opal-look predict image --engine yolo --model yolov8n "
    "--source https://example.com/frame.jpg --confidence 0.4"))


@predict.command("image")
def _predict_image(
        engine_id: str = typer.Option(..., "--engine"),
        model_id: str = typer.Option(..., "--model"),
        source: str = typer.Option(..., "--source",
                                   help="Local image path or permitted URI"),
        confidence: float = typer.Option(None, "--confidence"),
        device_id: str = typer.Option(None, "--device"),
        engine_options: str = typer.Option(None, "--options",
                                           help="JSON object of engine options"),
        include_native: bool = typer.Option(False, "--include-native")):
    body: dict = {"engine_id": engine_id, "model_id": model_id,
                  "source": source}
    if confidence is not None:
        body["confidence"] = confidence
    if device_id is not None:
        body["device_id"] = device_id
    if engine_options:
        body["engine_options"] = json.loads(engine_options)
    if include_native:
        body["include_native"] = True
    _emit(unwrap(_client().request("POST", "/api/v1/predict", json=body)))


app.add_typer(predict, name="predict")

# -- hardware --------------------------------------------------------------------

hardware = typer.Typer(help="hardware", epilog=(
    "Examples:\n"
    "  opal-look hardware list\n"
    "  opal-look hardware list --engine yolo\n"
    "  opal-look hardware show cpu --engine synthetic"))


@hardware.command("list")
def _hw_list(engine_id: str = typer.Option(None, "--engine")):
    _emit(unwrap(_client().get("/api/v1/hardware/" + _query(engine_id=engine_id))))


@hardware.command("show")
def _hw_show(device_id: str,
             engine_id: str = typer.Option(None, "--engine")):
    _emit(unwrap(_client().get(
        f"/api/v1/hardware/{device_id}" + _query(engine_id=engine_id))))


app.add_typer(hardware, name="hardware")

# -- stream ----------------------------------------------------------------------

stream = typer.Typer(help="stream", epilog=(
    "Examples:\n"
    "  opal-look stream start rtsp://cam.local/live\n"
    "  opal-look stream start rtsp://cam.local/live --engine yolo --model yolov8n\n"
    "  opal-look stream watch STREAM_ID\n"
    "  opal-look stream snapshot STREAM_ID --out frame.jpg"))


@stream.command("start")
def _stream_start(
        source: str = typer.Argument(..., help="rtsp:// or rtsps:// URI"),
        engine_id: str = typer.Option(None, "--engine"),
        model_id: str = typer.Option(None, "--model"),
        confidence: float = typer.Option(None, "--confidence"),
        device_id: str = typer.Option(None, "--device"),
        engine_options: str = typer.Option(None, "--options"),
        annotate: bool = typer.Option(False, "--annotate"),
        buffer_policy: str = typer.Option(None, "--buffer-policy"),
        buffer_size: int = typer.Option(None, "--buffer-size")):
    """Video-only without --engine; inference mode needs --engine + --model."""
    body: dict = {"source": source}
    if engine_id is not None:
        body["engine_id"] = engine_id
    if model_id is not None:
        body["model_id"] = model_id
    if confidence is not None:
        body["confidence"] = confidence
    if device_id is not None:
        body["device_id"] = device_id
    if engine_options:
        body["engine_options"] = json.loads(engine_options)
    if annotate:
        body["annotate"] = True
    if buffer_policy is not None:
        body["buffer_policy"] = buffer_policy
    if buffer_size is not None:
        body["buffer_size"] = buffer_size
    _emit(unwrap(_client().request("POST", "/api/v1/stream/", json=body)))


@stream.command("list")
def _stream_list():
    _emit(unwrap(_client().get("/api/v1/stream/")))


@stream.command("show")
def _stream_show(stream_id: str):
    _emit(unwrap(_client().get(f"/api/v1/stream/{stream_id}")))


@stream.command("stop")
def _stream_stop(stream_id: str):
    _emit(unwrap(_client().request(
        "POST", f"/api/v1/stream/{stream_id}/stop")))


@stream.command("watch")
def _stream_watch(stream_id: str):
    """Live detection/status events over SSE (Ctrl-C to detach)."""
    _stream_get(f"/api/v1/stream/{stream_id}/events", None, 0, sse=True)


@stream.command("watch-video")
def _stream_watch_video(
        stream_id: str,
        out: Path = typer.Option(None, "--out"),
        annotated: bool = typer.Option(False, "--annotated"),
        max_bytes: int = typer.Option(5_000_000, "--max-bytes")):
    q = "?annotated=true" if annotated else ""
    _stream_get(f"/api/v1/stream/{stream_id}/video{q}", out, max_bytes)


@stream.command("snapshot")
def _stream_snapshot(
        stream_id: str,
        out: Path = typer.Option(Path("snapshot.jpg"), "--out"),
        annotated: bool = typer.Option(False, "--annotated")):
    q = "?annotated=true" if annotated else ""
    data = unwrap(_client().get(f"/api/v1/stream/{stream_id}/snapshot{q}"))
    Path(out).write_bytes(data)
    typer.echo(str(out))


@stream.command("metrics")
def _stream_metrics(stream_id: str):
    _emit(unwrap(_client().get(f"/api/v1/stream/{stream_id}/metrics")))


app.add_typer(stream, name="stream")

# -- info ------------------------------------------------------------------------

info = typer.Typer(help="info", epilog=(
    "Examples:\n"
    "  opal-look info health\n"
    "  opal-look info version\n"
    "  opal-look info ping"))

info.command("health")(lambda: _emit(unwrap(_client().get("/api/v1/health/"))))
info.command("live")(lambda: _emit(unwrap(_client().get("/api/v1/health/live"))))
info.command("ready")(lambda: _emit(unwrap(_client().get("/api/v1/health/ready"))))
info.command("version")(lambda: _emit(unwrap(_client().get("/api/v1/info/"))))
info.command("ping")(lambda: _emit(unwrap(_client().get("/api/v1/info/ping"))))
app.add_typer(info, name="info")

# -- backup ----------------------------------------------------------------------

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
                   body: str = typer.Option(None, "--body")):
    """--file/--body supply the OpalConfigExport bundle; omitting both sends
    a null body (import the provisioned ./config/ file set)."""
    _emit(unwrap(_client().mutate("POST", "/api/v1/backup/import",
                                  json=_body(body, file))))


@backup.command("validate")
def _backup_validate(body: str = typer.Option(None, "--body"),
                     file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().request("POST", "/api/v1/backup/validate",
                                   json=_body(body, file))))


app.add_typer(backup, name="backup")

# -- service (REST first; local pidfile fallback when unreachable) ---------------

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

# -- config parent group ----------------------------------------------------------

config = typer.Typer(help="config", epilog=(
    "Examples:\n"
    "  opal-look config engine update synthetic --body '{\"enabled\":false}'\n"
    "  opal-look config profile add --file profile.json\n"
    "  opal-look config setting list\n"
    "  opal-look config setting set max_viewers 4"))

cfg_engine = typer.Typer(help="engine")


@cfg_engine.command("update")
def _cfg_engine_update(
        engine_id: str, body: str = typer.Option(None, "--body"),
        file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().mutate(
        "PATCH", f"/api/v1/engine/{engine_id}",
        etag_path=f"/api/v1/engine/{engine_id}", json=_body(body, file))))


config.add_typer(cfg_engine, name="engine")

_profs = _crud("profile", "/api/v1/profile/")


@_profs.command("activate")
def _prof_activate(profile_id: str):
    _emit(unwrap(_client().mutate(
        "POST", f"/api/v1/profile/{profile_id}/activate")))


config.add_typer(_profs, name="profile")

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


@setting.command("patch")
def _setting_patch(body: str = typer.Option(None, "--body"),
                   file: Path = typer.Option(None, "--file")):
    """Contract alias for `config setting update`."""
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
app.add_typer(config, name="config")

# -- top-level `setting` aliases (contract: 'setting get', 'setting delete') ------

setting_alias = typer.Typer(help="setting (alias spellings for config setting)")


@setting_alias.command("get")
def _setting_alias_get(key: str):
    """Alias for `config setting show`."""
    _emit(unwrap(_client().get(f"/api/v1/setting/{key}")))


@setting_alias.command("delete")
def _setting_alias_delete(key: str):
    """Alias for `config setting remove`."""
    _emit(unwrap(_client().mutate("DELETE", f"/api/v1/setting/{key}")))


app.add_typer(setting_alias, name="setting")

from . import tree_cmds as _tree_cmds  # noqa: E402
_tree_cmds.register(app, "opal-look")


def main() -> None:  # console script entry point
    app()


if __name__ == "__main__":
    main()

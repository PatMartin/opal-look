"""opal-look: thin REST client mirroring the v1.5 contract.

Group/verb layout follows the contract's x-opal-cli metadata:
add/remove/update/list/show plus operational verbs (view, observe,
stream, capture, probe, validate, frame, run, image, submit, cancel,
start, stop, download, export, import, status, live, ready, show).
All logic lives server-side; this client only issues HTTP calls and
honestly surfaces streaming/bearer limits.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from .client import ApiClient, unwrap

app = typer.Typer(
    help="OPAL Look v1.5 REST CLI (thin client; no business logic).",
    epilog=(
        "Examples:\n"
        "  opal-look health show\n"
        "  opal-look --json engines list\n"
        "  opal-look --url http://host:8000 sources list\n"
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


def _crud(name: str, base: str, epilog: str | None = None) -> typer.Typer:
    sub = typer.Typer(help=name, epilog=epilog)

    @sub.command("list")
    def _list():
        _emit(unwrap(_client().get(base)))

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


# -- CRUD resources -------------------------------------------------------------
app.add_typer(
    _crud("engines", "/api/v1/engine/", epilog=(
        "Examples:\n"
        "  opal-look engines list\n"
        "  opal-look engines show ENGINE_ID")),
    name="engines")
app.add_typer(
    _crud("models", "/api/v1/model/", epilog=(
        "Examples:\n"
        "  opal-look models list\n"
        "  opal-look models show synthetic-vision")),
    name="models")
_pipes = _crud("pipelines", "/api/v1/pipeline/", epilog=(
    "Examples:\n"
    "  opal-look pipelines list\n"
    "  opal-look pipelines add --file pipeline.json\n"
    "  opal-look pipelines validate --file pipeline.json\n"
    "  opal-look pipelines update PIPELINE_ID --file changes.json"))
_mons = _crud("monitors", "/api/v1/monitor/", epilog=(
    "Examples:\n"
    "  opal-look monitors add --file monitor.json\n"
    "  opal-look monitors stream MONITOR_ID    # tail SSE observations"))
app.add_typer(_pipes, name="pipelines")
app.add_typer(_mons, name="monitors")
app.add_typer(
    _crud("observations", "/api/v1/observation/", epilog=(
        "Examples:\n"
        "  opal-look observations list\n"
        "  opal-look observations show OBSERVATION_ID")),
    name="observations")

src = _crud("sources", "/api/v1/source/", epilog=(
    "Examples:\n"
    "  opal-look sources add --file camera.json\n"
    "  opal-look sources status SOURCE_ID\n"
    "  opal-look sources probe SOURCE_ID\n"
    "  opal-look sources frame SOURCE_ID --out frame.jpg\n"
    "  opal-look sources view SOURCE_ID --out clip.mjpeg\n"
    "  opal-look sources observe SOURCE_ID     # tail SSE observations\n"
    "  opal-look sources capture SOURCE_ID --annotated"))


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


@src.command("view")
def _src_view(source_id: str, out: Path = typer.Option(None, "--out"),
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


app.add_typer(src, name="sources")

@_pipes.command("validate")
def _pipe_validate(body: str = typer.Option(None, "--body"),
                   file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().request("POST", "/api/v1/pipeline/validate",
                                   json=_body(body, file))))


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

jobs = _crud("jobs", "/api/v1/job/", epilog=(
    "Examples:\n"
    "  opal-look jobs submit --file job.json --idempotency-key run-001\n"
    "  opal-look jobs list\n"
    "  opal-look jobs cancel JOB_ID"))


@jobs.command("submit")
def _job_submit(body: str = typer.Option(None, "--body"),
                file: Path = typer.Option(None, "--file"),
                idempotency_key: str = typer.Option(None, "--idempotency-key")):
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    _emit(unwrap(_client().request("POST", "/api/v1/job/",
                                   json=_body(body, file), headers=headers)))


@jobs.command("cancel")
def _job_cancel(job_id: str):
    _post_action(f"/api/v1/job/{job_id}/cancel")


app.add_typer(jobs, name="jobs")

med = _crud("media", "/api/v1/media/", epilog=(
    "Examples:\n"
    "  opal-look media upload frame.jpg --ttl 3600\n"
    "  opal-look media list\n"
    "  opal-look media download MEDIA_ID --out frame.jpg"))


@med.command("upload")
def _media_upload(file: Path, ttl_seconds: int = typer.Option(None, "--ttl")):
    data = {"ttl_seconds": ttl_seconds} if ttl_seconds else None
    with open(file, "rb") as fh:
        _emit(unwrap(_client().request("POST", "/api/v1/media/",
                                       files={"file": (file.name, fh)},
                                       data=data)))


app.add_typer(med, name="media")

rec = _crud("recordings", "/api/v1/recording/", epilog=(
    "Examples:\n"
    "  opal-look recordings start --source SOURCE_ID --duration 30\n"
    "  opal-look recordings stop RECORDING_ID\n"
    "  opal-look recordings list"))


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


@rec.command("stop")
def _rec_stop(recording_id: str):
    _emit(unwrap(_client().request(
        "POST", f"/api/v1/recording/{recording_id}/stop")))


app.add_typer(rec, name="recordings")

settings = _crud("settings", "/api/v1/setting/", epilog=(
    "Examples:\n"
    "  opal-look settings list\n"
    "  opal-look settings show max_upload_bytes\n"
    "  opal-look settings set max_viewers 4\n"
    "  opal-look settings reset max_viewers"))


@settings.command("set")
def _settings_set(key: str, value: str):
    _emit(unwrap(_client().mutate("PUT", f"/api/v1/setting/{key}",
                                  json={"value": json.loads(value)})))


@settings.command("reset")
def _settings_reset(key: str):
    _emit(unwrap(_client().mutate("DELETE", f"/api/v1/setting/{key}")))


app.add_typer(settings, name="settings")

config = typer.Typer(help="configuration", epilog=(
    "Examples:\n"
    "  opal-look configuration export\n"
    "  opal-look configuration validate --file config.json\n"
    "  opal-look configuration import --file config.json "
    "--bindings bindings.json"))


@config.command("export")
def _cfg_export():
    _emit(unwrap(_client().get("/api/v1/configuration/export")))


@config.command("validate")
def _cfg_validate(file: Path = typer.Option(..., "--file")):
    _emit(unwrap(_client().request("POST", "/api/v1/configuration/validate",
                                   json=json.loads(Path(file).read_text()))))


@config.command("import")
def _cfg_import(file: Path = typer.Option(..., "--file"),
                bindings: Path = typer.Option(None, "--bindings")):
    body = {"configuration": json.loads(Path(file).read_text())}
    if bindings:
        body["source_bindings"] = json.loads(Path(bindings).read_text())
    _emit(unwrap(_client().mutate("POST", "/api/v1/configuration/import",
                                  json=body)))


app.add_typer(config, name="configuration")

health = typer.Typer(help="health", epilog=(
    "Examples:\n"
    "  opal-look health show\n"
    "  opal-look health live\n"
    "  opal-look health ready"))
health.command("show")(lambda: _emit(unwrap(_client().get("/api/v1/health/"))))
health.command("live")(lambda: _emit(unwrap(_client().get("/api/v1/health/live"))))
health.command("ready")(lambda: _emit(unwrap(_client().get("/api/v1/health/ready"))))
app.add_typer(health, name="health")

metrics = typer.Typer(help="metrics", epilog=(
    "Examples:\n"
    "  opal-look metrics show"))
metrics.command("show")(lambda: _emit(unwrap(_client().get("/api/v1/metrics/"))))
app.add_typer(metrics, name="metrics")

events = typer.Typer(help="events", epilog=(
    "Examples:\n"
    "  opal-look events status"))
events.command("status")(lambda: _emit(unwrap(_client().get("/api/v1/events/status"))))
app.add_typer(events, name="events")

caps = typer.Typer(help="capabilities", epilog=(
    "Examples:\n"
    "  opal-look capabilities show"))
caps.command("show")(lambda: _emit(unwrap(_client().get("/api/v1/capabilities/"))))
app.add_typer(caps, name="capabilities")


# -- v1.5 upstream resources ------------------------------------------------

sessions = typer.Typer(help="sessions", epilog=(
    "Examples:\n"
    "  opal-look sessions start --body "
    "'{\"source_id\":\"cam\",\"pipeline_id\":\"p1\"}'\n"
    "  opal-look sessions list\n"
    "  opal-look sessions observations SESSION_ID\n"
    "  opal-look sessions preview SESSION_ID --out view.mjpeg"))


@sessions.command("start")
def _sess_start(body: str = typer.Option(None, "--body"),
                file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().mutate("POST", "/api/v1/session/",
                                  json=_body(body, file))))


@sessions.command("list")
def _sess_list():
    _emit(unwrap(_client().get("/api/v1/session/")))


@sessions.command("show")
def _sess_show(session_id: str):
    _emit(unwrap(_client().get(f"/api/v1/session/{session_id}")))


@sessions.command("stop")
def _sess_stop(session_id: str):
    _emit(unwrap(_client().request(
        "POST", f"/api/v1/session/{session_id}/stop")))


@sessions.command("observations")
def _sess_observations(session_id: str):
    _emit(unwrap(_client().get(
        f"/api/v1/session/{session_id}/observation/")))


@sessions.command("stream")
def _sess_stream(session_id: str):
    _stream_get(f"/api/v1/session/{session_id}/stream", None, 0, sse=True)


@sessions.command("preview")
def _sess_preview(session_id: str,
                  out: Path = typer.Option(None, "--out"),
                  max_bytes: int = typer.Option(5_000_000, "--max-bytes")):
    _stream_get(f"/api/v1/session/{session_id}/preview", out, max_bytes)


app.add_typer(sessions, name="sessions")

profiles = _crud("profiles", "/api/v1/profile/", epilog=(
    "Examples:\n"
    "  opal-look profiles add --body '{\"name\":\"night\",\"pipeline_id\":\"p1\"}'\n"
    "  opal-look profiles activate PROFILE_ID\n"
    "  opal-look profiles list"))


@profiles.command("activate")
def _prof_activate(profile_id: str):
    _emit(unwrap(_client().mutate(
        "POST", f"/api/v1/profile/{profile_id}/activate")))


app.add_typer(profiles, name="profiles")

app.add_typer(
    _crud("rules", "/api/v1/rule/", epilog=(
        "Examples:\n"
        "  opal-look rules add --body "
        "'{\"id\":\"r1\",\"name\":\"R\",\"source_id\":\"cam\",\"kind\":\"enters_zone\",\"zone_id\":\"z1\"}'\n"
        "  opal-look rules list\n"
        "  opal-look rules show r1")),
    name="rules")

app.add_typer(
    _crud("zones", "/api/v1/zone/", epilog=(
        "Examples:\n"
        "  opal-look zones add --body "
        "'{\"id\":\"z1\",\"source_id\":\"cam\",\"name\":\"Z\",\"kind\":\"polygon\",\"points\":[{\"x\":0,\"y\":0},{\"x\":1,\"y\":0},{\"x\":1,\"y\":1}]}'\n"
        "  opal-look zones list\n"
        "  opal-look zones show z1")),
    name="zones")

captures = typer.Typer(help="captures", epilog=(
    "Examples:\n"
    "  opal-look captures list\n"
    "  opal-look captures show CAPTURE_ID\n"
    "  opal-look captures download CAPTURE_ID --out cap.jpg"))


@captures.command("list")
def _cap_list(source_id: str = typer.Option(None, "--source")):
    q = f"?source_id={source_id}" if source_id else ""
    _emit(unwrap(_client().get(f"/api/v1/capture/{q}")))


@captures.command("show")
def _cap_show(capture_id: str):
    _emit(unwrap(_client().get(f"/api/v1/capture/{capture_id}")))


@captures.command("remove")
def _cap_remove(capture_id: str):
    _emit(unwrap(_client().mutate(
        "DELETE", f"/api/v1/capture/{capture_id}")))


@captures.command("download")
def _cap_download(capture_id: str,
                  out: Path = typer.Option(Path("capture.jpg"), "--out")):
    resp = unwrap(_client().request(
        "GET", f"/api/v1/capture/{capture_id}/content"))
    Path(out).write_bytes(resp)
    typer.echo(str(out))


app.add_typer(captures, name="captures")

artifacts = typer.Typer(help="artifacts", epilog=(
    "Examples:\n"
    "  opal-look artifacts list\n"
    "  opal-look artifacts show ARTIFACT_ID\n"
    "  opal-look artifacts download ARTIFACT_ID --out video.mjpeg"))


@artifacts.command("list")
def _art_list(kind: str = typer.Option(None, "--kind"),
              job_id: str = typer.Option(None, "--job")):
    q = "&".join(f"{k}={v}" for k, v in
                 (("kind", kind), ("job_id", job_id)) if v)
    _emit(unwrap(_client().get(f"/api/v1/artifact/{'?' + q if q else ''}")))


@artifacts.command("show")
def _art_show(artifact_id: str):
    _emit(unwrap(_client().get(f"/api/v1/artifact/{artifact_id}")))


@artifacts.command("remove")
def _art_remove(artifact_id: str):
    _emit(unwrap(_client().request(
        "DELETE", f"/api/v1/artifact/{artifact_id}")))


@artifacts.command("download")
def _art_download(artifact_id: str,
                  out: Path = typer.Option(Path("artifact.bin"), "--out")):
    resp = unwrap(_client().request(
        "GET", f"/api/v1/artifact/{artifact_id}/content"))
    Path(out).write_bytes(resp)
    typer.echo(str(out))


app.add_typer(artifacts, name="artifacts")


@app.command("info", epilog=(
    "Examples:\n"
    "  opal-look info"))
def _info():
    _emit(unwrap(_client().get("/")))


@app.command("tree", epilog=(
    "Examples:\n"
    "  opal-look tree"))
def _tree():
    """Print the full CLI command tree (options in [])."""
    import click
    import typer.main

    root = typer.main.get_command(app)

    def _usage_params(cmd):
        parts = []
        for p in cmd.params:
            if p.name == "help":
                continue
            opts = getattr(p, "opts", None) or []
            is_option = any(o.startswith("-") for o in opts) or \
                "Option" in type(p).__name__
            if is_option:
                name = next((o for o in opts if o.startswith("--")), p.name)
                meta = p.metavar or p.name.upper().replace("-", "_")
                val = "" if getattr(p, "is_flag", False) and not getattr(p, "flag_value", None) else f" {meta}"
                parts.append(f"[{name}{val}]")
            else:  # positional argument
                u = p.name.upper()
                parts.append(u if p.required else f"[{u}]")
        return (" " + " ".join(parts)) if parts else ""

    def _walk(cmd, prefix):
        if not hasattr(cmd, "commands"):
            return
        items = sorted(cmd.commands.items())
        for i, (name, sub) in enumerate(items):
            last = i == len(items) - 1
            branch = "`-- " if last else "|-- "
            typer.echo(f"{prefix}{branch}{name}{_usage_params(sub)}")
            _walk(sub, prefix + ("    " if last else "|   "))

    typer.echo("opal look")
    _walk(root, "")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

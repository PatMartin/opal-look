"""opal-look-cli: thin REST client mirroring the v1.5 contract.

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

app = typer.Typer(help="OPAL Look v1.5 REST CLI (thin client; no business logic).")

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


def _crud(name: str, base: str) -> typer.Typer:
    sub = typer.Typer(help=name)

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
    with _client().request("GET", path, stream=True) as resp:  # type: ignore[call-arg]
        if resp.status_code >= 400:
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
app.add_typer(_crud("engines", "/api/v1/engines/"), name="engines")
app.add_typer(_crud("models", "/api/v1/models/"), name="models")
_pipes = _crud("pipelines", "/api/v1/pipelines/")
_mons = _crud("monitors", "/api/v1/monitors/")
app.add_typer(_pipes, name="pipelines")
app.add_typer(_mons, name="monitors")
app.add_typer(_crud("observations", "/api/v1/observations/"), name="observations")

src = _crud("sources", "/api/v1/sources/")


@src.command("status")
def _src_status(source_id: str):
    _emit(unwrap(_client().get(f"/api/v1/sources/{source_id}/status")))


@src.command("probe")
def _src_probe(source_id: str):
    _post_action(f"/api/v1/sources/{source_id}/probe")


@src.command("frame")
def _src_frame(source_id: str, out: Path = typer.Option(Path("frame.jpg"), "--out")):
    data = unwrap(_client().get(f"/api/v1/sources/{source_id}/frame"))
    Path(out).write_bytes(data)
    typer.echo(str(out))


@src.command("view")
def _src_view(source_id: str, out: Path = typer.Option(None, "--out"),
              max_bytes: int = typer.Option(5_000_000, "--max-bytes"),
              pipeline_id: str = typer.Option(None, "--pipeline")):
    q = f"?pipeline_id={pipeline_id}" if pipeline_id else ""
    _stream_get(f"/api/v1/sources/{source_id}/stream{q}", out, max_bytes)


@src.command("observe")
def _src_observe(source_id: str):
    _stream_get(f"/api/v1/sources/{source_id}/observations/stream", None, 0,
                sse=True)


@src.command("capture")
def _src_capture(source_id: str, pipeline_id: str = typer.Option(None, "--pipeline"),
                 annotated: bool = typer.Option(False, "--annotated")):
    body = {}
    if pipeline_id:
        body["pipeline_id"] = pipeline_id
    if annotated:
        body["annotated"] = True
    _emit(unwrap(_client().request("POST",
                                   f"/api/v1/sources/{source_id}/capture",
                                   json=body or None)))


app.add_typer(src, name="sources")

@_pipes.command("validate")
def _pipe_validate(body: str = typer.Option(None, "--body"),
                   file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().request("POST", "/api/v1/pipelines/validate",
                                   json=_body(body, file))))


@_mons.command("stream")
def _mon_stream(monitor_id: str):
    _stream_get(f"/api/v1/monitors/{monitor_id}/observations/stream", None, 0,
                sse=True)


analyze = typer.Typer(help="analyze")


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

jobs = _crud("jobs", "/api/v1/jobs/")


@jobs.command("submit")
def _job_submit(body: str = typer.Option(None, "--body"),
                file: Path = typer.Option(None, "--file"),
                idempotency_key: str = typer.Option(None, "--idempotency-key")):
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    _emit(unwrap(_client().request("POST", "/api/v1/jobs/",
                                   json=_body(body, file), headers=headers)))


@jobs.command("cancel")
def _job_cancel(job_id: str):
    _post_action(f"/api/v1/jobs/{job_id}/cancel")


app.add_typer(jobs, name="jobs")

med = _crud("media", "/api/v1/media/")


@med.command("upload")
def _media_upload(file: Path, ttl_seconds: int = typer.Option(None, "--ttl")):
    data = {"ttl_seconds": ttl_seconds} if ttl_seconds else None
    with open(file, "rb") as fh:
        _emit(unwrap(_client().request("POST", "/api/v1/media/",
                                       files={"file": (file.name, fh)},
                                       data=data)))


@med.command("download")
def _media_download(media_id: str, out: Path = typer.Option(Path("media.bin"), "--out")):
    data = unwrap(_client().get(f"/api/v1/media/{media_id}/content"))
    Path(out).write_bytes(data)
    typer.echo(str(out))


app.add_typer(med, name="media")

rec = _crud("recordings", "/api/v1/recordings/")


@rec.command("start")
def _rec_start(source_id: str = typer.Option(..., "--source"),
               pipeline_id: str = typer.Option(None, "--pipeline"),
               max_duration_seconds: int = typer.Option(None, "--duration")):
    body = {"source_id": source_id}
    if pipeline_id:
        body["pipeline_id"] = pipeline_id
    if max_duration_seconds:
        body["max_duration_seconds"] = max_duration_seconds
    _emit(unwrap(_client().mutate("POST", "/api/v1/recordings/", json=body)))


@rec.command("stop")
def _rec_stop(recording_id: str):
    _emit(unwrap(_client().request(
        "POST", f"/api/v1/recordings/{recording_id}/stop")))


app.add_typer(rec, name="recordings")

settings = _crud("settings", "/api/v1/settings/")


@settings.command("set")
def _settings_set(key: str, value: str):
    _emit(unwrap(_client().mutate("PUT", f"/api/v1/settings/{key}",
                                  json={"value": json.loads(value)})))


@settings.command("reset")
def _settings_reset(key: str):
    _emit(unwrap(_client().mutate("DELETE", f"/api/v1/settings/{key}")))


app.add_typer(settings, name="settings")

config = typer.Typer(help="configuration")


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

health = typer.Typer(help="health")
health.command("show")(lambda: _emit(unwrap(_client().get("/api/v1/health/"))))
health.command("live")(lambda: _emit(unwrap(_client().get("/api/v1/health/live"))))
health.command("ready")(lambda: _emit(unwrap(_client().get("/api/v1/health/ready"))))
app.add_typer(health, name="health")

metrics = typer.Typer(help="metrics")
metrics.command("show")(lambda: _emit(unwrap(_client().get("/api/v1/metrics/"))))
app.add_typer(metrics, name="metrics")

events = typer.Typer(help="events")
events.command("status")(lambda: _emit(unwrap(_client().get("/api/v1/events/status"))))
app.add_typer(events, name="events")

caps = typer.Typer(help="capabilities")
caps.command("show")(lambda: _emit(unwrap(_client().get("/api/v1/capabilities/"))))
app.add_typer(caps, name="capabilities")


@app.command("info")
def _info():
    _emit(unwrap(_client().get("/")))


def main() -> None:
    app()


if __name__ == "__main__":
    main()

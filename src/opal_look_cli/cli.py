"""opal-look-cli: thin REST client for the OPAL Look API.

Resource verbs: list/show/add/update/remove; operational verbs:
activate/validate/upload/download/stream/export/import/stop/analyze.
All logic lives server-side; this client only issues HTTP calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from .client import ApiClient, unwrap

app = typer.Typer(help="OPAL Look REST CLI (thin client; no business logic).")

_state: dict = {
    "url": "http://127.0.0.1:8000", "json_out": False,
    "transport": None, "inner": None,
}


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


def _collection_app(name: str, base: str, rid: str | None = None) -> typer.Typer:
    """list/show/add/update/remove(+validate) over a config collection."""
    sub = typer.Typer(help=name)

    @sub.command("list")
    def _list():
        _emit(unwrap(_client().get(base)))

    @sub.command("show")
    def _show(resource_id: str):
        c = _client()
        _emit(unwrap(c.get(f"{base}{resource_id}")))

    @sub.command("add")
    def _add(body: str = typer.Option(None, "--body"), file: Path = typer.Option(None, "--file")):
        c = _client()
        _emit(unwrap(c.mutate("POST", base, json=_body(body, file))))

    @sub.command("update")
    def _update(resource_id: str, body: str = typer.Option(None, "--body"),
                file: Path = typer.Option(None, "--file")):
        c = _client()
        _emit(unwrap(c.mutate("PATCH", f"{base}{resource_id}",
                              etag_path=f"{base}{resource_id}", json=_body(body, file))))

    @sub.command("remove")
    def _remove(resource_id: str):
        c = _client()
        _emit(unwrap(c.mutate("DELETE", f"{base}{resource_id}",
                              etag_path=f"{base}{resource_id}")))

    @sub.command("validate")
    def _validate(resource_id: str):
        c = _client()
        _emit(unwrap(c.request("POST", f"{base}{resource_id}/validate")))
    return sub


app.add_typer(_collection_app("engines", "/api/v1/engines/"), name="engines")
app.add_typer(_collection_app("models", "/api/v1/models/"), name="models")
app.add_typer(_collection_app("sources", "/api/v1/sources/"), name="sources")

_profiles_app = _collection_app("profiles", "/api/v1/profiles/")


@_profiles_app.command("activate")
def _profiles_activate(profile_id: str):
    c = _client()
    _emit(unwrap(c.mutate("POST", f"/api/v1/profiles/{profile_id}/activate",
                          etag_path=f"/api/v1/profiles/{profile_id}")))


app.add_typer(_profiles_app, name="profiles")
_results_app = _collection_app("results", "/api/v1/results/")


@_results_app.command("snapshot")
def _results_snapshot(result_id: str, annotated: bool = typer.Option(False, "--annotated"),
                      retain: bool = typer.Option(False, "--retain"),
                      out: Path = typer.Option(None, "--out")):
    data = unwrap(_client().request(
        "POST", f"/api/v1/results/{result_id}/snapshot",
        json={"annotated": annotated, "retain": retain}))
    if retain:
        _emit(data)
    else:
        target = out or Path(f"{result_id}.jpg")
        Path(target).write_bytes(data)
        typer.echo(str(target))


app.add_typer(_results_app, name="results")
app.add_typer(_collection_app("snapshots", "/api/v1/snapshots/"), name="snapshots")


devices_app = typer.Typer(help="devices")


@devices_app.command("cameras")
def _cameras():
    _emit(unwrap(_client().get("/api/v1/devices/cameras/")))


app.add_typer(devices_app, name="devices")


settings_app = typer.Typer(help="settings")


@settings_app.command("show")
def _settings_show(key: str = typer.Argument(None)):
    c = _client()
    _emit(unwrap(c.get("/api/v1/settings/" + (key or ""))))


@settings_app.command("set")
def _settings_set(key: str, value: str):
    c = _client()
    _emit(unwrap(c.mutate("PUT", f"/api/v1/settings/{key}",
                          json={"value": json.loads(value)})))


@settings_app.command("unset")
def _settings_unset(key: str):
    c = _client()
    _emit(unwrap(c.mutate("DELETE", f"/api/v1/settings/{key}")))


app.add_typer(settings_app, name="settings")


media_app = typer.Typer(help="media")


@media_app.command("list")
def _media_list(cursor: str = typer.Option(None, "--cursor")):
    params = {"cursor": cursor} if cursor else None
    _emit(unwrap(_client().get("/api/v1/media/", params=params)))


@media_app.command("show")
def _media_show(media_id: str):
    _emit(unwrap(_client().get(f"/api/v1/media/{media_id}")))


@media_app.command("upload")
def _media_upload(file: Path):
    with open(file, "rb") as fh:
        _emit(unwrap(_client().request("POST", "/api/v1/media/",
                                      files={"file": (file.name, fh)})))


@media_app.command("download")
def _media_download(media_id: str, out: Path = typer.Option(Path("out.bin"), "--out")):
    data = unwrap(_client().get(f"/api/v1/media/{media_id}/content"))
    Path(out).write_bytes(data)
    typer.echo(str(out))


@media_app.command("remove")
def _media_remove(media_id: str):
    _emit(unwrap(_client().request("DELETE", f"/api/v1/media/{media_id}")))


app.add_typer(media_app, name="media")


analyze_app = typer.Typer(help="analyze")


@analyze_app.command("run")
def _analyze_run(body: str = typer.Option(None, "--body"),
                 file: Path = typer.Option(None, "--file")):
    _emit(unwrap(_client().request("POST", "/api/v1/analyze", json=_body(body, file))))


app.add_typer(analyze_app, name="analyze")


sessions_app = typer.Typer(help="sessions")


@sessions_app.command("list")
def _sessions_list(cursor: str = typer.Option(None, "--cursor"),
                   state: str = typer.Option(None, "--state")):
    params = {k: v for k, v in {"cursor": cursor, "state": state}.items() if v}
    _emit(unwrap(_client().get("/api/v1/sessions/", params=params or None)))


@sessions_app.command("show")
def _sessions_show(session_id: str):
    _emit(unwrap(_client().get(f"/api/v1/sessions/{session_id}")))


@sessions_app.command("add")
def _sessions_add(body: str = typer.Option(None, "--body"),
                  file: Path = typer.Option(None, "--file"),
                  idempotency_key: str = typer.Option(None, "--idempotency-key")):
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    _emit(unwrap(_client().request("POST", "/api/v1/sessions/",
                                  json=_body(body, file), headers=headers)))


@sessions_app.command("stop")
def _sessions_stop(session_id: str):
    _emit(unwrap(_client().request("POST", f"/api/v1/sessions/{session_id}/stop")))


@sessions_app.command("remove")
def _sessions_remove(session_id: str):
    _emit(unwrap(_client().request("DELETE", f"/api/v1/sessions/{session_id}")))


@sessions_app.command("latest")
def _sessions_latest(session_id: str):
    _emit(unwrap(_client().get(f"/api/v1/sessions/{session_id}/results/latest")))


@sessions_app.command("events")
def _sessions_events(session_id: str):
    resp = _client().get(f"/api/v1/sessions/{session_id}/events")
    typer.echo(resp.text)


@sessions_app.command("stream")
def _sessions_stream(session_id: str):
    resp = _client().get(f"/api/v1/sessions/{session_id}/results/events")
    typer.echo(resp.text)


app.add_typer(sessions_app, name="sessions")


backup_app = typer.Typer(help="backup")


@backup_app.command("export")
def _backup_export():
    _emit(unwrap(_client().get("/api/v1/backup/export")))


@backup_app.command("import")
def _backup_import(file: Path = typer.Option(..., "--file")):
    c = _client()
    _emit(unwrap(c.mutate("POST", "/api/v1/backup/import",
                          json=json.loads(Path(file).read_text()))))


@backup_app.command("validate")
def _backup_validate(file: Path = typer.Option(None, "--file")):
    c = _client()
    if file:
        _emit(unwrap(c.request("POST", "/api/v1/backup/validate",
                               json=json.loads(Path(file).read_text()))))
    else:
        _emit(unwrap(c.get("/api/v1/backup/validate")))


@backup_app.command("list")
def _backup_list():
    _emit(unwrap(_client().get("/api/v1/backup/list")))


@backup_app.command("create")
def _backup_create():
    _emit(unwrap(_client().request("POST", "/api/v1/backup/create")))


@backup_app.command("download")
def _backup_download(filename: str, out: Path = typer.Option(None, "--out")):
    data = unwrap(_client().get(f"/api/v1/backup/download/{filename}"))
    target = out or Path(filename)
    Path(target).write_text(json.dumps(data, indent=2))
    typer.echo(str(target))


@backup_app.command("restore")
def _backup_restore(filename: str):
    _emit(unwrap(_client().mutate("POST", f"/api/v1/backup/restore/{filename}")))


@backup_app.command("remove")
def _backup_remove(filename: str):
    _emit(unwrap(_client().request("DELETE", f"/api/v1/backup/{filename}")))


app.add_typer(backup_app, name="backup")


@app.command("health")
def _health():
    _emit(unwrap(_client().get("/api/v1/health/")))


@app.command("info")
def _info():
    _emit(unwrap(_client().get("/")))


def main() -> None:
    app()


if __name__ == "__main__":
    main()

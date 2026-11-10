"""v1.7.1 /service lifecycle (kernel service_start/stop/log pathItems).

Pidfile-managed: the managed server is the process in logs/opal_look.pid.
`start` doubles as restart — the replacement child waits for the old pid
to die before binding; when the managed process is this one, termination
is deferred until after the response is on the wire.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Query

from .. import service_control
from ..errors import ApiError

router = APIRouter()


def _status(state: str, pid: int | None,
            previous_pid: int | None) -> dict[str, Any]:
    return {
        "state": state,
        "pid": pid,
        "previous_pid": previous_pid,
        "log_file": str(service_control.log_path()),
    }


@router.post("/api/v1/service/start")
def post_api_v1_service_start(body: dict | None = None) -> dict[str, Any]:
    """OpalServiceStatus — launches the detached server; when a managed
    server is already running it is terminated, so start is a restart."""
    append = bool((body or {}).get("append"))
    managed = service_control.read_pid()
    previous = managed if managed is not None \
        and service_control.pid_alive(managed) else None
    new_pid = service_control.spawn_server(append=append, wait_pid=previous)
    if previous == os.getpid():
        # Self-restart: respond first, then exit so the child can bind.
        service_control.terminate_later()
    elif previous is not None:
        service_control.kill_pid(previous)
    return _status("running", new_pid, previous)


@router.post("/api/v1/service/stop")
def post_api_v1_service_stop() -> dict[str, Any]:
    """OpalServiceStatus — not an error when nothing is running."""
    managed = service_control.read_pid()
    if managed is None or not service_control.pid_alive(managed):
        service_control.pid_path().unlink(missing_ok=True)
        return _status("stopped", None, None)
    service_control.pid_path().unlink(missing_ok=True)
    if managed == os.getpid():
        service_control.terminate_later()
    else:
        service_control.kill_pid(managed)
    return _status("stopped", None, None)


@router.get("/api/v1/service/log")
def get_api_v1_service_log(
    lines: int = Query(10, ge=1, le=1000),
) -> dict[str, Any]:
    """OpalServiceLogTail — 404 when no service log exists."""
    tail = service_control.tail_log(lines)
    if tail is None:
        raise ApiError(404, "No service log at "
                            f"{service_control.log_path()}.")
    return {"log_file": str(service_control.log_path()), "lines": tail}

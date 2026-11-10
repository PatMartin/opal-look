"""Pidfile-managed service process control (logs/opal_look.{pid,log}).

The managed server is the process recorded in ``logs/opal_look.pid`` —
written by the launcher (``opal_look.main``) at startup and by
:func:`spawn_server` for the detached child. The REST surface and the
CLI both act on that record; when the serving process is not the managed
one, the reported state stays honest.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FILE = "opal_look.log"
PID_FILE = "opal_look.pid"
WAIT_PID_ENV = "OPAL_LOOK_WAIT_PID"


def log_dir() -> Path:
    return LOG_DIR


def log_path() -> Path:
    return log_dir() / LOG_FILE


def pid_path() -> Path:
    return log_dir() / PID_FILE


def read_pid() -> int | None:
    try:
        return int(pid_path().read_text().strip())
    except (OSError, ValueError):
        return None


def write_pid(pid: int) -> None:
    log_dir().mkdir(parents=True, exist_ok=True)
    pid_path().write_text(f"{pid}\n")


def ensure_pidfile() -> None:
    """Register the running process as the managed server."""
    write_pid(os.getpid())


def release_pidfile() -> None:
    """Clear the pidfile only when it still names this process."""
    if read_pid() == os.getpid():
        pid_path().unlink(missing_ok=True)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_death(pid: int, timeout: float = 30.0) -> None:
    """Block until ``pid`` exits — used by a restarted child so the old
    server releases its port before the new one binds."""
    deadline = time.monotonic() + timeout
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)


def kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def terminate_later(delay: float = 1.0) -> None:
    """Self-terminate after ``delay`` seconds — the response must be on the
    wire before the process exits. Abrupt on purpose: long-lived streams
    (SSE/MJPEG) must not stall the stop."""

    def _go() -> None:
        time.sleep(delay)
        os._exit(0)

    threading.Thread(target=_go, daemon=True).start()


def tail_log(lines: int) -> list[str] | None:
    """Trailing log lines, oldest first; None when no log file exists."""
    path = log_path()
    if not path.is_file():
        return None
    return path.read_text(errors="replace").splitlines()[-lines:]


def spawn_server(append: bool = False, wait_pid: int | None = None,
                 env_extra: dict | None = None) -> int:
    """Launch ``python -m opal_look.main`` detached with output to the
    service log; record the child pid and return it."""
    log_dir().mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if wait_pid:
        env[WAIT_PID_ENV] = str(wait_pid)
    if env_extra:
        env.update(env_extra)
    log = log_path().open("a" if append else "w")
    kwargs: dict = {"stdout": log, "stderr": subprocess.STDOUT, "env": env}
    if sys.platform == "win32":
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-m", "opal_look.main"], **kwargs)
    log.close()
    write_pid(proc.pid)
    return proc.pid

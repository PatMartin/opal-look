"""Server-managed backup archives under <data_dir>/backups/.

A backup is a single JSON file holding the OpalConfigExport bundle —
portable logical configuration only (redacted locators, no secrets, no
runtime state). Filenames are generated server-side and validated against
the kernel BackupFilename rules (no separators, no traversal) plus an
in-directory containment check.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ApiError
from .store import Store
from .timeutil import iso, now_iso

_KERNEL_NAME_RE = re.compile(r"^[^/\\]{1,255}$")


def backup_dir(store: Store) -> Path:
    d = Path(store.data_dir) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def check_backup_filename(name: str) -> None:
    """Kernel BackupFilename: 1..255 chars, no separators or traversal."""
    if not _KERNEL_NAME_RE.match(name) or name in (".", "..") \
            or ".." in Path(name).parts:
        raise ApiError(422, "Invalid backup filename.")


def backup_path(store: Store, filename: str) -> Path:
    check_backup_filename(filename)
    path = (backup_dir(store) / filename).resolve()
    if path.parent != backup_dir(store).resolve():
        raise ApiError(422, "Invalid backup filename.")
    if not path.is_file():
        raise ApiError(404, f"Backup {filename!r} not found.")
    return path


def backup_read(path: Path) -> dict[str, Any]:
    """Kernel OpalBackupInfo."""
    stat = path.stat()
    return {
        "filename": path.name,
        "created_at": iso(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
        "size_bytes": stat.st_size,
    }


def list_backups(store: Store) -> list[dict[str, Any]]:
    rows = [backup_read(p) for p in backup_dir(store).glob("*.json")]
    rows.sort(key=lambda b: (b["created_at"], b["filename"]), reverse=True)
    return rows


def create_backup(store: Store) -> str:
    """Write opal-look-<UTCts>.json holding the export bundle; return name."""
    from .configuration import build_export

    d = backup_dir(store)
    stamp = now_iso().replace(":", "").replace("-", "").split(".")[0]
    name = f"opal-look-{stamp}Z.json"
    path = d / name
    for seq in range(2, 100):
        if not path.exists():
            break
        name = f"opal-look-{stamp}Z-{seq}.json"
        path = d / name
    bundle = build_export(store)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    tmp.replace(path)
    return name


def read_backup(store: Store, filename: str) -> dict[str, Any]:
    """Parse a managed backup into a configuration bundle."""
    path = backup_path(store, filename)
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError(422, f"Backup {filename!r} is not a readable "
                            f"configuration bundle: {exc}")
    if not isinstance(bundle, dict):
        raise ApiError(422, f"Backup {filename!r} is not a JSON object.")
    return bundle

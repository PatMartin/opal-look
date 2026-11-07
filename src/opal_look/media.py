"""Media decode/validation and MediaRead assembly.

Bytes are validated and decoded before acceptance: JPEG/PNG via Pillow
(EXIF orientation applied for reported dimensions). Video requires an
installed decoder; none is installed, so MP4/other containers -> 415.
"""

from __future__ import annotations

import io
import re
import sqlite3
from pathlib import Path
from typing import Any

from .errors import ApiError
from .timeutil import expired, iso, now_iso

_IMAGE_MAGIC = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png"}


def sanitize_filename(name: str | None) -> str:
    base = (name or "upload").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(". ")
    return base or "upload"


def detect_and_decode(data: bytes, max_pixels: int) -> dict[str, Any]:
    """Return {kind, content_type, width, height, duration_ms} or raise."""
    if not data:
        raise ApiError(422, "Empty upload.")
    for magic, ctype in _IMAGE_MAGIC.items():
        if data.startswith(magic):
            return _decode_image(data, ctype, max_pixels)
    if len(data) > 12 and data[4:8] == b"ftyp":
        # v1.5 accepts bounded video uploads for storage/download; decode is
        # still unavailable (no MP4/H.264 decoder installed).
        return {"kind": "upload_video", "content_type": "video/mp4",
                "width": None, "height": None, "duration_ms": None}
    raise ApiError(415, "Unsupported media type: expected image (JPEG/PNG) or MP4 video bytes.")


def _decode_image(data: bytes, content_type: str, max_pixels: int) -> dict[str, Any]:
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as img:
            oriented = ImageOps.exif_transpose(img)
            width, height = oriented.size
    except Exception:
        raise ApiError(422, "Image bytes could not be decoded (corrupt media).")
    if width * height > max_pixels:
        raise ApiError(
            413,
            f"Decoded image exceeds the pixel limit ({width * height} > {max_pixels}).",
        )
    return {
        "kind": "upload_image",
        "content_type": content_type,
        "width": width,
        "height": height,
        "duration_ms": None,
    }


def media_dir(data_dir: Path) -> Path:
    path = data_dir / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_read(row: sqlite3.Row) -> dict[str, Any]:
    """Upstream Media resource: {id,kind(image|video),mime_type,size_bytes,
    created_at,expires_at,duration_ms?}."""
    mime = row["content_type"] or "application/octet-stream"
    return {
        "id": row["media_id"],
        "kind": "image" if mime.startswith("image/") else "video",
        "mime_type": mime,
        "size_bytes": row["size_bytes"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "duration_ms": row["duration_ms"],
    }


def create_media(store, data: bytes, *, kind: str, origin: str,
                 filename: str = "upload",
                 content_type: str | None = None,
                 source_id=None, job_id=None, monitor_id=None,
                 annotated: bool = False, width=None, height=None,
                 duration_ms=None, expires_at: str | None = None) -> str:
    """Internal service: write immutable media bytes + row. Returns media_id."""
    import hashlib
    import secrets as _secrets

    media_id = f"media-{_secrets.token_hex(8)}"
    path = media_dir(store.data_dir) / media_id
    path.write_bytes(data)
    if expires_at is None:
        from .settings import effective_settings
        from datetime import timedelta as _td
        from .timeutil import parse_iso as _parse
        ttl = int(effective_settings(store).media_retention_hours * 3600)
        expires_at = iso(_parse(now_iso()) + _td(seconds=ttl))
    store.media.insert({
        "media_id": media_id, "filename": sanitize_filename(filename),
        "kind": kind,
        "content_type": content_type or "application/octet-stream",
        "size_bytes": len(data), "path": str(path),
        "width": width, "height": height, "duration_ms": duration_ms,
        "created_at": now_iso(), "expires_at": expires_at,
        "origin": origin, "source_id": source_id, "job_id": job_id,
        "monitor_id": monitor_id, "annotated": 1 if annotated else 0,
        "sha256": hashlib.sha256(data).hexdigest(),
    })
    return media_id


def is_expired(row: sqlite3.Row) -> bool:
    return expired(row["expires_at"])

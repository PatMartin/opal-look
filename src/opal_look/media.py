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
from .timeutil import expired

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
        raise ApiError(
            415,
            "Video uploads are unsupported: no MP4/H.264 decoder is installed.",
        )
    raise ApiError(415, "Unsupported media type: expected JPEG or PNG image bytes.")


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
        "kind": "image",
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
    return {
        "media_id": row["media_id"],
        "filename": row["filename"],
        "kind": row["kind"],
        "content_type": row["content_type"],
        "size_bytes": row["size_bytes"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "width": row["width"],
        "height": row["height"],
        "duration_ms": row["duration_ms"],
    }


def is_expired(row: sqlite3.Row) -> bool:
    return expired(row["expires_at"])

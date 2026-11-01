"""Snapshot annotation rendering and SnapshotRead assembly."""

from __future__ import annotations

import sqlite3
from typing import Any


def snapshot_read(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "snapshot_id": row["snapshot_id"],
        "result_id": row["result_id"],
        "annotated": bool(row["annotated"]),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "content_type": "image/jpeg",
        "width": row["width"],
        "height": row["height"],
    }


def annotate(image: Any, result: dict[str, Any]) -> Any:
    """Overlay the result payload on a copy of the exact analyzed frame."""
    from PIL import ImageDraw

    out = image.copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    task = result["task"]
    payload = result["payload"]

    def box_rect(box: dict) -> tuple[float, float, float, float]:
        return (
            box["x"] * w,
            box["y"] * h,
            (box["x"] + box["width"]) * w,
            (box["y"] + box["height"]) * h,
        )

    def label(item: dict) -> str:
        return f"{item['label']} {item['confidence']:.2f}"

    if task == "detection":
        for obj in payload["objects"]:
            draw.rectangle(box_rect(obj["box"]), outline="red", width=2)
            draw.text((obj["box"]["x"] * w, obj["box"]["y"] * h), label(obj), fill="red")
    elif task == "classification":
        for i, cls in enumerate(payload["classes"]):
            draw.text((4, 4 + i * 12), label(cls), fill="yellow")
    elif task == "segmentation" and payload.get("kind") == "instance":
        for inst in payload["instances"]:
            draw.rectangle(box_rect(inst["box"]), outline="cyan", width=2)
            draw.text((inst["box"]["x"] * w, inst["box"]["y"] * h), label(inst), fill="cyan")
    elif task == "pose":
        for pose in payload["poses"]:
            draw.rectangle(box_rect(pose["box"]), outline="lime", width=2)
            for kp in pose["keypoints"]:
                if kp["x"] is not None:
                    x, y = kp["x"] * w, kp["y"] * h
                    draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill="lime")
    elif task == "ocr":
        for region in payload["regions"]:
            pts = [(p["x"] * w, p["y"] * h) for p in region["polygon"]]
            draw.polygon(pts, outline="magenta")
            draw.text(pts[0], region["text"], fill="magenta")
    return out

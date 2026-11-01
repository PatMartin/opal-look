"""Bounded ephemeral exact-frame cache (not durable storage).

Maps result_id -> (PIL image, result dict, expiry). Entries evict on TTL
or capacity pressure; snapshot capture fails with 409 frame_unavailable
rather than substituting another frame.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass
class FrameEntry:
    image: Any
    result: dict[str, Any]
    expires_at_epoch: float


class FrameCache:
    def __init__(self, capacity: int = 64) -> None:
        self._capacity = capacity
        self._entries: OrderedDict[str, FrameEntry] = OrderedDict()

    def put(
        self, result_id: str, image: Any, result: dict[str, Any], ttl_seconds: int
    ) -> None:
        self._entries[result_id] = FrameEntry(
            image=image, result=result, expires_at_epoch=time.monotonic() + ttl_seconds
        )
        self._entries.move_to_end(result_id)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def get(self, result_id: str) -> FrameEntry | None:
        entry = self._entries.get(result_id)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at_epoch:
            del self._entries[result_id]
            return None
        self._entries.move_to_end(result_id)
        return entry

"""Profile read shape (kernel OpalProfile) + compartment validation.

Look's own compartment (`modules.opal-look`) is an explicit empty closed
schema: registered and round-tripped, but any member is rejected. Declared
foreign compartments are validated structurally against the kernel
namespace schemas; unrecognized module ids are preserved verbatim.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .errors import ApiError

OWN_COMPARTMENT = "opal-look"
# Compartments whose namespace is a closed empty schema today.
_EMPTY_COMPARTMENTS = {"opal-look", "opal-look-yolo", "opal-event", "opal-think"}

_NUM = (int, float)


def _is_num(v: Any) -> bool:
    return isinstance(v, _NUM) and not isinstance(v, bool)


def _say_field(key: str, v: Any) -> bool:
    if key in ("voice_id", "output_format"):
        return isinstance(v, str) and bool(v)
    if key == "sample_rate":
        return v is None or (isinstance(v, int) and not isinstance(v, bool)
                             and 8000 <= v <= 192000)
    if key == "speed":
        return _is_num(v) and 0.25 <= v <= 4.0
    if key == "volume":
        return _is_num(v) and 0.0 <= v <= 2.0
    if key == "engine_options":
        return isinstance(v, dict)
    return False


_SAY_FIELDS = {"voice_id", "speed", "volume", "output_format",
               "sample_rate", "engine_options"}
_LISTEN_STR_ARRAYS = {"wakeword_names", "enabled_intents", "enabled_slots"}
_LISTEN_OBJS = {"confidence_thresholds", "vad_settings"}


def _validate_compartment(module_id: str, compartment: Any, patch: bool) -> None:
    """Structural validation of one compartment (kernel namespace rules)."""
    where = f"modules.{module_id}"
    if not isinstance(compartment, dict):
        raise ApiError(422, f"{where} must be an object.")
    if module_id in _EMPTY_COMPARTMENTS:
        if compartment:
            raise ApiError(
                422, f"{where} declares no fields; any member is rejected.")
        return
    if module_id == "opal-say":
        for k, v in compartment.items():
            if k not in _SAY_FIELDS:
                raise ApiError(422, f"Unknown field {where}.{k}.")
            if patch and v is None:
                continue  # explicit null removes an override
            if not _say_field(k, v):
                raise ApiError(422, f"Invalid value for {where}.{k}.")
        return
    if module_id == "opal-listen":
        for k, v in compartment.items():
            if k not in (_LISTEN_STR_ARRAYS | _LISTEN_OBJS | {"model_paths"}):
                raise ApiError(422, f"Unknown field {where}.{k}.")
            if patch and v is None:
                continue
            ok = (
                (k in _LISTEN_STR_ARRAYS
                 and isinstance(v, list)
                 and all(isinstance(x, str) for x in v))
                or (k in _LISTEN_OBJS and isinstance(v, dict))
                or (k == "model_paths" and isinstance(v, dict)
                    and all(isinstance(x, str) for x in v.values()))
            )
            if not ok:
                raise ApiError(422, f"Invalid value for {where}.{k}.")
        return
    # Unrecognized module ids: any well-formed object is preserved verbatim.


def validate_modules(modules: Any, *, patch: bool) -> None:
    if modules is None:
        return
    if not isinstance(modules, dict):
        raise ApiError(422, "modules must be an object.")
    if patch:
        foreign = set(modules) - {OWN_COMPARTMENT}
        if foreign:
            raise ApiError(
                422, "Profile patches may only edit the opal-look "
                     f"compartment; rejected: {sorted(foreign)}.")
    for module_id, compartment in modules.items():
        _validate_compartment(module_id, compartment, patch)


def validate_shared(shared: Any) -> None:
    """OpalProfileShared is a closed empty object: any member is rejected."""
    if shared is None:
        return
    if not isinstance(shared, dict):
        raise ApiError(422, "shared must be an object.")
    if shared:
        raise ApiError(
            422, "shared declares no fields; any member is rejected.")


def profile_read(row: sqlite3.Row) -> dict:
    """Kernel OpalProfile: complete portable document + local is_active."""
    return {
        "id": row["profile_id"],
        "name": row["name"],
        "description": row["description"],
        "is_active": bool(row["active"]),
        "shared": json.loads(row["shared"] or "{}"),
        "modules": json.loads(row["modules"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

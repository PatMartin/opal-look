"""Remote Ultralytics YOLO engine, wired via OPAL_LOOK_ENGINE_YOLO_* env.

OPAL_LOOK_ENGINE_YOLO_BASE_URL registers the remote adapter and is seeded
into the engines table at startup (authoritative over PATCH changes).
ENABLED / TIMEOUT_SECONDS follow; TOKEN stays env-only. See env.py and
docs/YOLO_INSTALL.md.
"""

from __future__ import annotations

import json
import logging

from ...store import Store
from .adapter import YoloRemoteAdapter
from .env import ENGINE_ID, env_base_url, env_config, env_enabled

_log = logging.getLogger(__name__)


def register_if_configured(registry) -> bool:
    """Register the remote adapter when the env declares a BASE_URL."""
    if env_base_url() is None or ENGINE_ID in registry:
        return False
    registry.register(YoloRemoteAdapter())
    _log.info("registered remote yolo engine (%s)", env_base_url())
    return True


def apply_env(store: Store) -> bool:
    """Seed the yolo engines row from env (authoritative, every boot).

    Rewrites config/enabled when they differ and bumps the config revision;
    no-op when nothing changed or the adapter isn't registered.
    """
    if env_base_url() is None:
        return False
    row = store.engines.get(ENGINE_ID)
    if row is None:
        return False
    fields: dict = {}
    desired_config = env_config()
    if json.loads(row["config"]) != desired_config:
        fields["config"] = desired_config
    if (enabled := env_enabled()) is not None \
            and bool(row["enabled"]) != enabled:
        fields["enabled"] = enabled
    if not fields:
        return False
    with store.write_txn():
        store.engines.update(ENGINE_ID, fields)
        store.bump_revision()
    _log.info("applied yolo engine config from environment: %s",
              ", ".join(sorted(fields)))
    return True


__all__ = ["ENGINE_ID", "YoloRemoteAdapter", "apply_env",
           "register_if_configured"]

"""Per-aggregate repositories behind Protocols, sharing one connection
and the Store.write_txn unit of work."""

from .engines import EngineRepository, SqliteEngineRepository
from .meta import MetaRepository, SqliteMetaRepository, new_revision
from .profiles import ProfileRepository, SqliteProfileRepository
from .settings import SettingsRepository, SqliteSettingsRepository

__all__ = [
    "EngineRepository",
    "MetaRepository",
    "ProfileRepository",
    "SettingsRepository",
    "SqliteEngineRepository",
    "SqliteMetaRepository",
    "SqliteProfileRepository",
    "SqliteSettingsRepository",
    "new_revision",
]

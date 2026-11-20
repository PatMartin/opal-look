"""Per-aggregate repositories behind Protocols, sharing one connection
and the Store.write_txn unit of work."""

from .engines import EngineRepository, SqliteEngineRepository
from .meta import MetaRepository, SqliteMetaRepository, new_revision
from .personas import PersonaRepository, SqlitePersonaRepository
from .profiles import ProfileRepository, SqliteProfileRepository
from .settings import SettingsRepository, SqliteSettingsRepository

__all__ = [
    "EngineRepository",
    "MetaRepository",
    "PersonaRepository",
    "ProfileRepository",
    "SettingsRepository",
    "SqliteEngineRepository",
    "SqliteMetaRepository",
    "SqlitePersonaRepository",
    "SqliteProfileRepository",
    "SqliteSettingsRepository",
    "new_revision",
]

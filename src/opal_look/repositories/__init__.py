"""Per-aggregate repositories behind Protocols, sharing one connection
and the Store.write_txn unit of work."""

from .engines import EngineRepository, SqliteEngineRepository
from .media import MediaRepository, SqliteMediaRepository
from .meta import MetaRepository, SqliteMetaRepository, new_revision
from .models import ModelRepository, SqliteModelRepository
from .profiles import ProfileRepository, SqliteProfileRepository
from .results import ResultRepository, SqliteResultRepository
from .settings import SettingsRepository, SqliteSettingsRepository
from .sources import SourceRepository, SqliteSourceRepository

__all__ = [
    "EngineRepository",
    "MediaRepository",
    "MetaRepository",
    "ModelRepository",
    "ProfileRepository",
    "ResultRepository",
    "SettingsRepository",
    "SourceRepository",
    "SqliteEngineRepository",
    "SqliteMediaRepository",
    "SqliteMetaRepository",
    "SqliteModelRepository",
    "SqliteProfileRepository",
    "SqliteResultRepository",
    "SqliteSettingsRepository",
    "SqliteSourceRepository",
    "new_revision",
]

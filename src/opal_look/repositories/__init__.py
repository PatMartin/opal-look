"""Per-aggregate repositories behind Protocols, sharing one connection
and the Store.write_txn unit of work."""

from .engines import EngineRepository, SqliteEngineRepository
from .media import MediaRepository, SqliteMediaRepository
from .meta import MetaRepository, SqliteMetaRepository, new_revision
from .models import ModelRepository, SqliteModelRepository
from .monitors import MonitorRepository, SqliteMonitorRepository
from .observations import ObservationRepository, SqliteObservationRepository
from .pipelines import PipelineRepository, SqlitePipelineRepository
from .profiles import ProfileRepository, SqliteProfileRepository
from .results import ResultRepository, SqliteResultRepository
from .sessions import SessionRepository, SqliteSessionRepository
from .settings import SettingsRepository, SqliteSettingsRepository
from .snapshots import SnapshotRepository, SqliteSnapshotRepository
from .sources import SourceRepository, SqliteSourceRepository

__all__ = [
    "EngineRepository",
    "MediaRepository",
    "MetaRepository",
    "ModelRepository",
    "MonitorRepository",
    "ObservationRepository",
    "PipelineRepository",
    "ProfileRepository",
    "ResultRepository",
    "SettingsRepository",
    "SessionRepository",
    "SnapshotRepository",
    "SourceRepository",
    "SqliteEngineRepository",
    "SqliteMediaRepository",
    "SqliteMetaRepository",
    "SqliteModelRepository",
    "SqliteMonitorRepository",
    "SqliteObservationRepository",
    "SqlitePipelineRepository",
    "SqliteProfileRepository",
    "SqliteResultRepository",
    "SqliteSettingsRepository",
    "SqliteSessionRepository",
    "SqliteSnapshotRepository",
    "SqliteSourceRepository",
    "new_revision",
]

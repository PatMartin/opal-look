"""Per-aggregate repositories behind Protocols, sharing one connection
and the Store.write_txn unit of work."""

from .engines import EngineRepository, SqliteEngineRepository
from .media import MediaRepository, SqliteMediaRepository
from .meta import MetaRepository, SqliteMetaRepository, new_revision
from .models import ModelRepository, SqliteModelRepository
from .recordings import RecordingRepository, SqliteRecordingRepository
from .jobs import JobRepository, SqliteJobRepository
from .monitors import MonitorRepository, SqliteMonitorRepository
from .observations import ObservationRepository, SqliteObservationRepository
from .pipelines import PipelineRepository, SqlitePipelineRepository
from .profiles import ProfileRepository, SqliteProfileRepository
from .zones import SqliteZoneRepository, ZoneRepository
from .rules import SqliteRuleRepository, RuleRepository
from .artifacts import SqliteArtifactRepository, ArtifactRepository
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
    "JobRepository",
    "RecordingRepository",
    "MonitorRepository",
    "ObservationRepository",
    "PipelineRepository",
    "ProfileRepository",
    "ZoneRepository",
    "RuleRepository",
    "ArtifactRepository",
    "ResultRepository",
    "SettingsRepository",
    "SessionRepository",
    "SnapshotRepository",
    "SourceRepository",
    "SqliteEngineRepository",
    "SqliteMediaRepository",
    "SqliteMetaRepository",
    "SqliteModelRepository",
    "SqliteJobRepository",
    "SqliteRecordingRepository",
    "SqliteMonitorRepository",
    "SqliteObservationRepository",
    "SqlitePipelineRepository",
    "SqliteProfileRepository",
    "SqliteZoneRepository",
    "SqliteRuleRepository",
    "SqliteArtifactRepository",
    "ArtifactRepository",
    "RuleRepository",
    "ArtifactRepository",
    "ZoneRepository",
    "RuleRepository",
    "ArtifactRepository",
    "SqliteResultRepository",
    "SqliteSettingsRepository",
    "SqliteSessionRepository",
    "SqliteSnapshotRepository",
    "SqliteSourceRepository",
    "new_revision",
]

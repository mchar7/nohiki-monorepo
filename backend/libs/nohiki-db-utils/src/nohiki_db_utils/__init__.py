"""Database utilities for the Nohiki platform."""

from __future__ import annotations

from importlib.util import find_spec

from .async_db import (
    DatabaseDependencies,
    close_all_engines,
    db_session,
    get_async_engine,
    get_async_sessionmaker,
    reset_db,
)
from .db_mixins import (
    SQL_NOW,
    UUID_DEFAULT,
    AuditMixin,
    BaseEntity,
    CreatedAtMixin,
    IdMixin,
    RepresentableMixin,
    SchemaMixin,
    UpdatedAtMixin,
    UserAuditMixin,
    UserBaseEntity,
    UUIDPrimaryKeyMixin,
)
from .event_metadata import EVENT_VERSION, create_event_metadata
from .freshness import FreshnessTrackingMixin
from .fts import build_prefix_tsquery
from .health import DatabaseHealthProbe, ensure_database_ready
from .idempotency import check_and_mark_processed
from .idempotency_migrations import (
    get_cleanup_processed_events_sql,
    get_create_processed_events_index_sql,
    get_create_processed_events_sql,
)
from .metrics import DatabaseMetrics, get_database_metrics
from .outbox import OutboxBatchWriter, OutboxEntry, OutboxEventParams, OutboxWriter
from .outbox_health import OutboxHealthProbe
from .outbox_metrics import OutboxMetrics, get_outbox_metrics
from .pagination import PaginationResult, paginate_query
from .saga import SagaBaseMixin, SagaRepository, SagaStatus, StaleSagaDetector
from .settings import DatabaseMixin, DatabaseSettings
from .state_machine import InvalidTransitionError, StateMachineMixin

_HAS_ALEMBIC = find_spec("alembic") is not None

if _HAS_ALEMBIC:
    from .alembic_env import (
        configure_offline_context,
        create_schema_if_not_exists,
        get_sync_database_url,
        run_online_migrations,
    )
    from .migrations import (
        MigrationState,
        get_migration_state,
        initialize_database,
        run_migrations_with_coordination,
        skip_migrations,
    )

__version__ = "0.1.0"

__all__ = [
    "EVENT_VERSION",
    "SQL_NOW",
    "UUID_DEFAULT",
    "AuditMixin",
    "BaseEntity",
    "CreatedAtMixin",
    "DatabaseDependencies",
    "DatabaseHealthProbe",
    "DatabaseMetrics",
    "DatabaseMixin",
    "DatabaseSettings",
    "FreshnessTrackingMixin",
    "IdMixin",
    "InvalidTransitionError",
    "OutboxBatchWriter",
    "OutboxEntry",
    "OutboxEventParams",
    "OutboxHealthProbe",
    "OutboxMetrics",
    "OutboxWriter",
    "PaginationResult",
    "RepresentableMixin",
    "SagaBaseMixin",
    "SagaRepository",
    "SagaStatus",
    "SchemaMixin",
    "StaleSagaDetector",
    "StateMachineMixin",
    "UUIDPrimaryKeyMixin",
    "UpdatedAtMixin",
    "UserAuditMixin",
    "UserBaseEntity",
    "build_prefix_tsquery",
    "check_and_mark_processed",
    "close_all_engines",
    "create_event_metadata",
    "db_session",
    "ensure_database_ready",
    "get_async_engine",
    "get_async_sessionmaker",
    "get_cleanup_processed_events_sql",
    "get_create_processed_events_index_sql",
    "get_create_processed_events_sql",
    "get_database_metrics",
    "get_outbox_metrics",
    "paginate_query",
    "reset_db",
]

if _HAS_ALEMBIC:
    __all__ += [
        "MigrationState",
        "configure_offline_context",
        "create_schema_if_not_exists",
        "get_migration_state",
        "get_sync_database_url",
        "initialize_database",
        "run_migrations_with_coordination",
        "run_online_migrations",
        "skip_migrations",
    ]

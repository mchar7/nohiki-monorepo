"""Database utilities for the Nohiki platform."""

from __future__ import annotations

import importlib
from importlib.util import find_spec
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nohiki_db_utils.async_db import (
        DatabaseDependencies as DatabaseDependencies,
    )
    from nohiki_db_utils.async_db import (
        close_all_engines as close_all_engines,
    )
    from nohiki_db_utils.async_db import db_session as db_session
    from nohiki_db_utils.async_db import get_async_engine as get_async_engine
    from nohiki_db_utils.async_db import (
        get_async_sessionmaker as get_async_sessionmaker,
    )
    from nohiki_db_utils.async_db import reset_db as reset_db
    from nohiki_db_utils.db_mixins import SQL_NOW as SQL_NOW
    from nohiki_db_utils.db_mixins import UUID_DEFAULT as UUID_DEFAULT
    from nohiki_db_utils.db_mixins import AuditMixin as AuditMixin
    from nohiki_db_utils.db_mixins import BaseEntity as BaseEntity
    from nohiki_db_utils.db_mixins import CreatedAtMixin as CreatedAtMixin
    from nohiki_db_utils.db_mixins import IdMixin as IdMixin
    from nohiki_db_utils.db_mixins import RepresentableMixin as RepresentableMixin
    from nohiki_db_utils.db_mixins import SchemaMixin as SchemaMixin
    from nohiki_db_utils.db_mixins import UpdatedAtMixin as UpdatedAtMixin
    from nohiki_db_utils.db_mixins import UserAuditMixin as UserAuditMixin
    from nohiki_db_utils.db_mixins import UserBaseEntity as UserBaseEntity
    from nohiki_db_utils.db_mixins import (
        UUIDPrimaryKeyMixin as UUIDPrimaryKeyMixin,
    )
    from nohiki_db_utils.event_metadata import EVENT_VERSION as EVENT_VERSION
    from nohiki_db_utils.event_metadata import (
        create_event_metadata as create_event_metadata,
    )
    from nohiki_db_utils.freshness import (
        FreshnessTrackingMixin as FreshnessTrackingMixin,
    )
    from nohiki_db_utils.fts import build_prefix_tsquery as build_prefix_tsquery
    from nohiki_db_utils.health import DatabaseHealthProbe as DatabaseHealthProbe
    from nohiki_db_utils.health import (
        ensure_database_ready as ensure_database_ready,
    )
    from nohiki_db_utils.idempotency import (
        check_and_mark_processed as check_and_mark_processed,
    )
    from nohiki_db_utils.idempotency_migrations import (
        get_cleanup_processed_events_sql as get_cleanup_processed_events_sql,
    )
    from nohiki_db_utils.idempotency_migrations import (
        get_create_processed_events_index_sql as get_create_processed_events_index_sql,
    )
    from nohiki_db_utils.idempotency_migrations import (
        get_create_processed_events_sql as get_create_processed_events_sql,
    )
    from nohiki_db_utils.metrics import DatabaseMetrics as DatabaseMetrics
    from nohiki_db_utils.metrics import (
        get_database_metrics as get_database_metrics,
    )
    from nohiki_db_utils.outbox import OutboxBatchWriter as OutboxBatchWriter
    from nohiki_db_utils.outbox import OutboxEntry as OutboxEntry
    from nohiki_db_utils.outbox import OutboxEventParams as OutboxEventParams
    from nohiki_db_utils.outbox import OutboxWriter as OutboxWriter
    from nohiki_db_utils.outbox_health import OutboxHealthProbe as OutboxHealthProbe
    from nohiki_db_utils.outbox_metrics import OutboxMetrics as OutboxMetrics
    from nohiki_db_utils.outbox_metrics import (
        get_outbox_metrics as get_outbox_metrics,
    )
    from nohiki_db_utils.pagination import PaginationResult as PaginationResult
    from nohiki_db_utils.pagination import paginate_query as paginate_query
    from nohiki_db_utils.saga import SagaBaseMixin as SagaBaseMixin
    from nohiki_db_utils.saga import SagaRepository as SagaRepository
    from nohiki_db_utils.saga import SagaStatus as SagaStatus
    from nohiki_db_utils.saga import StaleSagaDetector as StaleSagaDetector
    from nohiki_db_utils.settings import DatabaseMixin as DatabaseMixin
    from nohiki_db_utils.settings import DatabaseSettings as DatabaseSettings
    from nohiki_db_utils.state_machine import (
        InvalidTransitionError as InvalidTransitionError,
    )
    from nohiki_db_utils.state_machine import (
        StateMachineMixin as StateMachineMixin,
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

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "DatabaseDependencies": ("nohiki_db_utils.async_db", "DatabaseDependencies"),
    "close_all_engines": ("nohiki_db_utils.async_db", "close_all_engines"),
    "db_session": ("nohiki_db_utils.async_db", "db_session"),
    "get_async_engine": ("nohiki_db_utils.async_db", "get_async_engine"),
    "get_async_sessionmaker": ("nohiki_db_utils.async_db", "get_async_sessionmaker"),
    "reset_db": ("nohiki_db_utils.async_db", "reset_db"),
    "SQL_NOW": ("nohiki_db_utils.db_mixins", "SQL_NOW"),
    "UUID_DEFAULT": ("nohiki_db_utils.db_mixins", "UUID_DEFAULT"),
    "AuditMixin": ("nohiki_db_utils.db_mixins", "AuditMixin"),
    "BaseEntity": ("nohiki_db_utils.db_mixins", "BaseEntity"),
    "CreatedAtMixin": ("nohiki_db_utils.db_mixins", "CreatedAtMixin"),
    "IdMixin": ("nohiki_db_utils.db_mixins", "IdMixin"),
    "RepresentableMixin": ("nohiki_db_utils.db_mixins", "RepresentableMixin"),
    "SchemaMixin": ("nohiki_db_utils.db_mixins", "SchemaMixin"),
    "UpdatedAtMixin": ("nohiki_db_utils.db_mixins", "UpdatedAtMixin"),
    "UserAuditMixin": ("nohiki_db_utils.db_mixins", "UserAuditMixin"),
    "UserBaseEntity": ("nohiki_db_utils.db_mixins", "UserBaseEntity"),
    "UUIDPrimaryKeyMixin": ("nohiki_db_utils.db_mixins", "UUIDPrimaryKeyMixin"),
    "EVENT_VERSION": ("nohiki_db_utils.event_metadata", "EVENT_VERSION"),
    "create_event_metadata": ("nohiki_db_utils.event_metadata", "create_event_metadata"),
    "FreshnessTrackingMixin": ("nohiki_db_utils.freshness", "FreshnessTrackingMixin"),
    "build_prefix_tsquery": ("nohiki_db_utils.fts", "build_prefix_tsquery"),
    "DatabaseHealthProbe": ("nohiki_db_utils.health", "DatabaseHealthProbe"),
    "ensure_database_ready": ("nohiki_db_utils.health", "ensure_database_ready"),
    "check_and_mark_processed": ("nohiki_db_utils.idempotency", "check_and_mark_processed"),
    "get_cleanup_processed_events_sql": (
        "nohiki_db_utils.idempotency_migrations",
        "get_cleanup_processed_events_sql",
    ),
    "get_create_processed_events_index_sql": (
        "nohiki_db_utils.idempotency_migrations",
        "get_create_processed_events_index_sql",
    ),
    "get_create_processed_events_sql": (
        "nohiki_db_utils.idempotency_migrations",
        "get_create_processed_events_sql",
    ),
    "DatabaseMetrics": ("nohiki_db_utils.metrics", "DatabaseMetrics"),
    "get_database_metrics": ("nohiki_db_utils.metrics", "get_database_metrics"),
    "OutboxBatchWriter": ("nohiki_db_utils.outbox", "OutboxBatchWriter"),
    "OutboxEntry": ("nohiki_db_utils.outbox", "OutboxEntry"),
    "OutboxEventParams": ("nohiki_db_utils.outbox", "OutboxEventParams"),
    "OutboxWriter": ("nohiki_db_utils.outbox", "OutboxWriter"),
    "OutboxHealthProbe": ("nohiki_db_utils.outbox_health", "OutboxHealthProbe"),
    "OutboxMetrics": ("nohiki_db_utils.outbox_metrics", "OutboxMetrics"),
    "get_outbox_metrics": ("nohiki_db_utils.outbox_metrics", "get_outbox_metrics"),
    "PaginationResult": ("nohiki_db_utils.pagination", "PaginationResult"),
    "paginate_query": ("nohiki_db_utils.pagination", "paginate_query"),
    "SagaBaseMixin": ("nohiki_db_utils.saga", "SagaBaseMixin"),
    "SagaRepository": ("nohiki_db_utils.saga", "SagaRepository"),
    "SagaStatus": ("nohiki_db_utils.saga", "SagaStatus"),
    "StaleSagaDetector": ("nohiki_db_utils.saga", "StaleSagaDetector"),
    "DatabaseMixin": ("nohiki_db_utils.settings", "DatabaseMixin"),
    "DatabaseSettings": ("nohiki_db_utils.settings", "DatabaseSettings"),
    "InvalidTransitionError": ("nohiki_db_utils.state_machine", "InvalidTransitionError"),
    "StateMachineMixin": ("nohiki_db_utils.state_machine", "StateMachineMixin"),
}

_HAS_ALEMBIC = find_spec("alembic") is not None

if _HAS_ALEMBIC:
    if TYPE_CHECKING:
        from nohiki_db_utils.alembic_env import (
            configure_offline_context as configure_offline_context,
        )
        from nohiki_db_utils.alembic_env import (
            create_schema_if_not_exists as create_schema_if_not_exists,
        )
        from nohiki_db_utils.alembic_env import (
            get_sync_database_url as get_sync_database_url,
        )
        from nohiki_db_utils.alembic_env import (
            run_online_migrations as run_online_migrations,
        )
        from nohiki_db_utils.migrations import MigrationState as MigrationState
        from nohiki_db_utils.migrations import (
            get_migration_state as get_migration_state,
        )
        from nohiki_db_utils.migrations import (
            initialize_database as initialize_database,
        )
        from nohiki_db_utils.migrations import (
            run_migrations_with_coordination as run_migrations_with_coordination,
        )
        from nohiki_db_utils.migrations import skip_migrations as skip_migrations

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
    _LAZY_IMPORTS |= {
        "MigrationState": ("nohiki_db_utils.migrations", "MigrationState"),
        "configure_offline_context": ("nohiki_db_utils.alembic_env", "configure_offline_context"),
        "create_schema_if_not_exists": ("nohiki_db_utils.alembic_env", "create_schema_if_not_exists"),
        "get_migration_state": ("nohiki_db_utils.migrations", "get_migration_state"),
        "get_sync_database_url": ("nohiki_db_utils.alembic_env", "get_sync_database_url"),
        "initialize_database": ("nohiki_db_utils.migrations", "initialize_database"),
        "run_migrations_with_coordination": (
            "nohiki_db_utils.migrations",
            "run_migrations_with_coordination",
        ),
        "run_online_migrations": ("nohiki_db_utils.alembic_env", "run_online_migrations"),
        "skip_migrations": ("nohiki_db_utils.migrations", "skip_migrations"),
    }


def __getattr__(name: str) -> object:
    """Lazy-import database components (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)

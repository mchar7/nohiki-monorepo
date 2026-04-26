"""Alembic environment configuration for user-auth-service."""

import logging

from alembic import context
from nohiki_db_utils import (
    configure_offline_context,
    get_sync_database_url,
    run_online_migrations,
)
from user_auth_service.db.models import Base

config = context.config

if config.config_file_name is not None:
    # Skip fileConfig() which destroys structlog/observability logging pipeline
    logging.getLogger("alembic").setLevel(logging.INFO)

target_metadata = Base.metadata
VERSION_TABLE_SCHEMA = "user_auth_schema"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_sync_database_url(config)
    configure_offline_context(
        url=url,
        target_metadata=target_metadata,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = get_sync_database_url(config)
    run_online_migrations(
        url=url,
        target_metadata=target_metadata,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

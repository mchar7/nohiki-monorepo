"""Alembic environment for job-ingest-discovery-service."""

import logging

from alembic import context
from nohiki_db_utils import (
    configure_offline_context,
    get_sync_database_url,
    run_online_migrations,
)
from sqlalchemy import MetaData

config = context.config
if config.config_file_name is not None:
    logging.getLogger("alembic").setLevel(logging.INFO)

target_metadata = MetaData()
VERSION_TABLE_SCHEMA = "job_ingest_discovery_schema"


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    configure_offline_context(
        url=get_sync_database_url(config),
        target_metadata=target_metadata,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    run_online_migrations(
        url=get_sync_database_url(config),
        target_metadata=target_metadata,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

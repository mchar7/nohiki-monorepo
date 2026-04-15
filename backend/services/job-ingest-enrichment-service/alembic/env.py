"""Alembic environment configuration for job-ingest-enrichment-service."""

import logging

from alembic import context
from nohiki_db_utils.alembic_env import (
    configure_offline_context,
    get_sync_database_url,
    run_online_migrations,
)

from job_ingest_enrichment_service.db.models import Base

config = context.config

if config.config_file_name is not None:
    # Skip fileConfig() which destroys structlog/observability logging pipeline
    logging.getLogger("alembic").setLevel(logging.INFO)

target_metadata = Base.metadata

_SCHEMA = "job_ingest_enrichment_schema"

if context.is_offline_mode():
    _url = get_sync_database_url(config)
    configure_offline_context(_url, target_metadata, version_table_schema=_SCHEMA)
else:
    _url = get_sync_database_url(config)
    run_online_migrations(_url, target_metadata, version_table_schema=_SCHEMA)

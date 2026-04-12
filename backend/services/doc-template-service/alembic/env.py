"""Alembic environment configuration for doc-template-service."""

import logging

from alembic import context
from doc_template_service.db.models import Base
from nohiki_db_utils import (
    configure_offline_context,
    get_sync_database_url,
    run_online_migrations,
)

config = context.config

if config.config_file_name is not None:
    # Skip fileConfig() which destroys structlog/observability logging pipeline
    logging.getLogger("alembic").setLevel(logging.INFO)

target_metadata = Base.metadata

_SCHEMA = "doc_template_schema"

if context.is_offline_mode():
    _url = get_sync_database_url(config)
    configure_offline_context(_url, target_metadata, version_table_schema=_SCHEMA)
else:
    _url = get_sync_database_url(config)
    run_online_migrations(_url, target_metadata, version_table_schema=_SCHEMA)

"""Database version checking and migration necessity determination.

Handles Alembic revision detection and retry logic for transient connection errors.
"""

from __future__ import annotations

import time

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from nohiki_observability import get_logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from .state import MigrationError
from .url_utils import to_sync_url

logger = get_logger(__name__)

DB_CONNECTION_MAX_RETRIES = 10
DB_CONNECTION_RETRY_DELAY = 3


def is_transient_error(err: OperationalError) -> bool:
    """Check if a database error is transient and worth retrying."""
    err_str = str(err).lower()
    return any(
        pattern in err_str
        for pattern in (
            "name or service not known",
            "connection refused",
            "could not connect",
            "failed to resolve",
            "timeout",
        )
    )


def get_current_revision_from_connection(
    connection: Connection,
    version_table_schema: str | None,
) -> str | None:
    """Get current alembic revision from an open connection."""
    if not version_table_schema:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()

    schema_exists = connection.execute(
        text("SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema)"),
        {"schema": version_table_schema},
    ).scalar()

    if not schema_exists:
        logger.info(
            "Version table schema does not exist",
            schema=version_table_schema,
        )
        return None

    context = MigrationContext.configure(
        connection,
        opts={"version_table_schema": version_table_schema},
    )
    return context.get_current_revision()


def get_db_version_info(
    db_url: str,
    config_path: str,
    *,
    max_retries: int = DB_CONNECTION_MAX_RETRIES,
    retry_delay: float = DB_CONNECTION_RETRY_DELAY,
) -> tuple[str | None, str | None]:
    """Get current DB version and target (head) version with retry for transient errors.

    Reads version_table_schema from alembic.ini if present to check the correct schema.
    Returns (None, head_rev) if schema or version table doesn't exist.

    Raises:
        MigrationError: If connection fails after all retries (transient error).

    """
    sync_url = to_sync_url(db_url)
    cfg = Config(config_path)
    cfg.set_main_option("script_location", "alembic")
    version_table_schema = cfg.get_main_option("version_table_schema")

    script = ScriptDirectory.from_config(cfg)
    head_rev = script.get_current_head()

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        engine = None
        try:
            engine = create_engine(sync_url)
            with engine.connect() as connection:
                current_rev = get_current_revision_from_connection(connection, version_table_schema)
        except OperationalError as err:
            last_error = err
            if is_transient_error(err) and attempt < max_retries:
                logger.warning(
                    "Database connection failed (transient), retrying",
                    attempt=attempt,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    error=str(err)[:200],
                )
                time.sleep(retry_delay)
                continue

            logger.exception(
                "Database connection failed after retries",
                attempts=attempt,
                error=str(err)[:200],
            )
            msg = f"Cannot connect to database after {attempt} attempts: {err}"
            raise MigrationError(msg) from err

        except Exception as err:
            logger.exception("Unexpected error checking DB version")
            msg = f"Failed to check DB version: {err}"
            raise MigrationError(msg) from err

        else:
            return current_rev, head_rev

        finally:
            if engine is not None:
                engine.dispose()

    msg = f"Cannot connect to database after {max_retries} attempts: {last_error}"
    raise MigrationError(msg)


def check_migration_needed(
    database_url: str,
    alembic_config_path: str,
    service_name: str,
) -> tuple[bool, str | None]:
    """Check if migrations are needed. Returns (needs_migration, head_rev)."""
    current_rev, head_rev = get_db_version_info(database_url, alembic_config_path)

    if current_rev is None:
        logger.info(
            "Database not initialized (no alembic_version table)",
            service=service_name,
            target_version=head_rev,
        )
        return True, head_rev

    if current_rev == head_rev:
        logger.info(
            "DATABASE ALREADY UP TO DATE - skipping migration",
            service=service_name,
            current_version=current_rev,
            target_version=head_rev,
        )
        return False, head_rev

    logger.info(
        "Database requires migration",
        service=service_name,
        current_version=current_rev,
        target_version=head_rev,
    )
    return True, head_rev

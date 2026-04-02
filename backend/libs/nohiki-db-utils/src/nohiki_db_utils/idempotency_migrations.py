"""SQL generation for processed_events table used by handler-level idempotency."""

from __future__ import annotations

from string import Template

from ._validators import validate_schema_name


def get_create_processed_events_sql(schema: str) -> str:
    """Generate SQL to create the processed_events table.

    Args:
        schema: Database schema name.

    Returns:
        SQL string to create the processed_events table.

    Raises:
        ValueError: If `schema` is not a safe SQL identifier.

    """
    validate_schema_name(schema)
    return f"""
        CREATE TABLE IF NOT EXISTS {schema}.processed_events (
            event_id UUID NOT NULL,
            handler_name VARCHAR(255) NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (event_id, handler_name)
        )
    """


def get_create_processed_events_index_sql(schema: str) -> str:
    """Generate index for TTL cleanup queries on processed_events.

    Args:
        schema: Database schema name.

    Returns:
        SQL string to create the index.

    Raises:
        ValueError: If `schema` is not a safe SQL identifier.

    """
    validate_schema_name(schema)
    return f"""
        CREATE INDEX IF NOT EXISTS idx_{schema}_processed_events_processed_at
        ON {schema}.processed_events (processed_at)
    """


def get_cleanup_processed_events_sql(schema: str, retention_hours: int = 168) -> str:
    """Generate SQL to clean up old processed_events (default: 7 days).

    Args:
        schema: Database schema name.
        retention_hours: Hours to retain processed events before cleanup.

    Returns:
        SQL string to delete old processed events.

    Raises:
        ValueError: If `schema` is not a safe SQL identifier.

    """
    validate_schema_name(schema)
    tmpl = Template("DELETE FROM $schema.processed_events WHERE processed_at < NOW() - INTERVAL '$hours hours'")
    return tmpl.substitute(schema=schema, hours=retention_hours)

"""SQL generation helpers for outbox table migrations.

Services use these helpers in their Alembic migrations to create
outbox tables in their own schema. This ensures:
1. DRY - common SQL in one place
2. Isolation - each service's outbox in its own schema
3. No conflicts - even if services share a database

Usage in service Alembic migration:
    from nohiki_db_utils.outbox_migrations import (
        get_create_outbox_table_sql,
        get_create_outbox_indexes_sql,
    )

    def upgrade():
        # Create outbox in service's schema
        op.execute(get_create_outbox_table_sql("my_service_schema"))
        op.execute(get_create_outbox_indexes_sql("my_service_schema"))

"""

from __future__ import annotations

from nohiki_db_utils._validators import validate_schema_name


def get_create_outbox_table_sql(schema: str) -> str:
    """Generate SQL to create the outbox table for Debezium CDC.

    The outbox table stores events that Debezium captures via PostgreSQL
    WAL (Write-Ahead Log) and publishes to Kafka topics. Column names
    match Debezium's Outbox Event Router SMT expectations.

    Args:
        schema: The schema name (e.g., 'user_pref_schema').

    Returns:
        SQL string to create the outbox table.

    """
    validate_schema_name(schema)
    return f"""
        CREATE TABLE IF NOT EXISTS {schema}.outbox (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            aggregatetype VARCHAR(255) NOT NULL,
            aggregateid VARCHAR(255) NOT NULL,
            type VARCHAR(255) NOT NULL,
            payload BYTEA NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            tracingspancontext VARCHAR(256)
        )
    """


def get_create_outbox_indexes_sql(schema: str) -> str:
    """Generate SQL to create indexes on the outbox table.

    Creates an index on timestamp for Debezium's incremental snapshot
    and for debugging/monitoring queries.

    Args:
        schema: The schema name.

    Returns:
        SQL string to create the index.

    """
    validate_schema_name(schema)
    return f"""
        CREATE INDEX IF NOT EXISTS ix_{schema}_outbox_timestamp
            ON {schema}.outbox (timestamp)
    """

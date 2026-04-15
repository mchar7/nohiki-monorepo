"""Initial migration for job-ingest-enrichment-service.

Creates the job_ingest_enrichment_schema with:
- enrichment_embedding_saga table (convergence tracking for embedding callbacks)
- outbox table (Debezium CDC for atomic event publishing)
- processed_events table (idempotency tracking)

Revision ID: 001
Revises:
Create Date: 2026-02-23
"""

from collections.abc import Sequence
from typing import Final

from alembic import op
from nohiki_db_utils.idempotency_migrations import (
    get_create_processed_events_index_sql,
    get_create_processed_events_sql,
)
from nohiki_db_utils.outbox_migrations import (
    get_create_outbox_indexes_sql,
    get_create_outbox_table_sql,
)

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_NAME: Final[str] = "job_ingest_enrichment_schema"


def upgrade() -> None:
    """Create job-ingest-enrichment schema and all tables."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    # ════════════════════════════════════════════════════════════════════════════
    # enrichment_embedding_saga table
    # Tracks convergence of parallel embedding callbacks during enrichment
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.enrichment_embedding_saga (
            -- Primary key (UUIDv7)
            id UUID PRIMARY KEY DEFAULT uuidv7(),

            -- Domain-specific columns
            listing_id VARCHAR(36) NOT NULL,
            enrichment_data_json TEXT NOT NULL,
            llm_model_id VARCHAR(255) NOT NULL,
            collection_version VARCHAR(10) NOT NULL,
            retrieval_embedding_b64 TEXT,
            title_embedding_b64 TEXT,
            skills_embedding_b64 TEXT,

            -- SagaBaseMixin columns (from nohiki_db_utils.saga)
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED', 'EXPIRED')),
            expected_callbacks INTEGER NOT NULL
                CHECK (expected_callbacks >= 1),
            received_callbacks INTEGER NOT NULL DEFAULT 0
                CHECK (received_callbacks >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
                CHECK (version >= 1)
        )
    """)

    # Index for listing lookups
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_enrichment_saga_listing_id
        ON {SCHEMA_NAME}.enrichment_embedding_saga (listing_id)
    """)

    # Partial index for pending sagas (most queries filter on status)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_enrichment_saga_status_pending
        ON {SCHEMA_NAME}.enrichment_embedding_saga (status)
        WHERE status = 'PENDING'
    """)

    # Index for stale saga detection (cleanup job)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_enrichment_saga_expires
        ON {SCHEMA_NAME}.enrichment_embedding_saga (expires_at)
        WHERE status = 'PENDING'
    """)

    # BRIN for time-series access patterns
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_enrichment_saga_created_at_brin
        ON {SCHEMA_NAME}.enrichment_embedding_saga USING BRIN (created_at)
        WITH (pages_per_range = 32)
    """)

    op.execute(f"""
        COMMENT ON TABLE {SCHEMA_NAME}.enrichment_embedding_saga IS
        'Saga tracking convergence of parallel embedding requests during job enrichment. '
        'Created when skill normalization completes; completed when all embedding callbacks arrive.'
    """)

    # ════════════════════════════════════════════════════════════════════════════
    # Outbox and processed_events tables (shared infrastructure)
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(get_create_outbox_table_sql(SCHEMA_NAME))
    op.execute(get_create_outbox_indexes_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop job-ingest-enrichment schema and all tables."""
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")

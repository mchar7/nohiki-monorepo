"""
Initial migration for job-ingest-schedule-service.

Schema: job_schedule_schema
Tables: ingestion_schedules

Revision ID: 001
Revises:
Create Date: 2025-12-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from nohiki_db_utils.idempotency_migrations import (
    get_create_processed_events_index_sql,
    get_create_processed_events_sql,
)
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_NAME = "job_schedule_schema"
NOW_DEFAULT = sa.func.now()
EMPTY_VARCHAR_ARRAY = sa.text("ARRAY[]::varchar[]")


def upgrade() -> None:
    """Create job_schedule_schema and tables."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    work_arrangement_enum = postgresql.ENUM(
        "UNSPECIFIED", "ON_SITE", "HYBRID", "REMOTE",
        name="work_arrangement_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    work_arrangement_enum.create(op.get_bind(), checkfirst=True)

    job_board_source_enum = postgresql.ENUM(
        "UNSPECIFIED", "INDEED", "LINKEDIN", "ZIPRECRUITER",
        "GOOGLE", "GLASSDOOR", "BAYT", "NAUKRI",
        "COMPANY_WEBSITE",
        name="job_board_source_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    job_board_source_enum.create(op.get_bind(), checkfirst=True)

    # Create ingestion_schedules table
    op.create_table(
        "ingestion_schedules",
        # Primary key - matches query_id from job-query-composition-service events
        sa.Column("query_id", postgresql.UUID(), nullable=False),
        # Denormalized query parameters (from scrape_query.*.v1 events)
        sa.Column("search_keywords", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("locations", postgresql.JSONB(), nullable=False),
        sa.Column(
            "work_arrangements",
            postgresql.ARRAY(work_arrangement_enum),
            nullable=False,
            server_default=sa.text("ARRAY[]::job_schedule_schema.work_arrangement_enum[]"),
        ),
        sa.Column(
            "remote_preferences",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=EMPTY_VARCHAR_ARRAY,
        ),
        sa.Column(
            "sources",
            postgresql.ARRAY(job_board_source_enum),
            nullable=False,
            server_default=sa.text("ARRAY[]::job_schedule_schema.job_board_source_enum[]"),
        ),
        # Backend-controlled parameters (NOT from events)
        sa.Column("hours_old", sa.Integer(), nullable=False, server_default=sa.text("72")),
        sa.Column("results_wanted", sa.Integer(), nullable=False, server_default=sa.text("50")),
        # Scheduling state
        sa.Column("frequency", sa.Interval(), nullable=False, server_default=sa.text("'1 day'::interval")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        # Standard timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        # Primary key
        sa.PrimaryKeyConstraint("query_id"),
        # IS JSON constraint for JSONB validation
        sa.CheckConstraint("locations IS JSON ARRAY", name="chk_locations_json_array"),
        sa.CheckConstraint(
            "frequency > INTERVAL '0 seconds'",
            name="ck_schedule_frequency_positive",
        ),
        schema=SCHEMA_NAME,
    )

    # Index for efficient cron queries: find active schedules due for execution
    # Partial index on (next_run_at) WHERE is_active = true
    op.create_index(
        "idx_schedules_due",
        "ingestion_schedules",
        ["next_run_at"],
        schema=SCHEMA_NAME,
        postgresql_where=sa.text("is_active = true AND next_run_at IS NOT NULL"),
    )

    # Hash index for is_active equality lookups
    op.execute(
        f"CREATE INDEX idx_schedules_active_hash ON {SCHEMA_NAME}.ingestion_schedules USING HASH (is_active)"
    )

    # BRIN index on created_at for time-range queries (schedules are append-mostly)
    op.execute(
        f"CREATE INDEX idx_schedules_created_at_brin ON {SCHEMA_NAME}.ingestion_schedules "
        "USING BRIN (created_at) WITH (pages_per_range = 32)"
    )

    # Add table comment
    op.execute(
        f"COMMENT ON TABLE {SCHEMA_NAME}.ingestion_schedules IS "
        "'Materialized ingestion schedules from job-query-composition-service events.'"
    )

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))



def downgrade() -> None:
    """Drop all job schedule application objects."""
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA_NAME}.processed_events CASCADE")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA_NAME}.ingestion_schedules CASCADE")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA_NAME}.job_board_source_enum")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA_NAME}.work_arrangement_enum")

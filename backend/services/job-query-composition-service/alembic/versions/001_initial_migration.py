"""
Initial migration for job-query-composition-service.

Schema: job_query_schema
Tables: ingestion_queries, query_contributors, outbox

Revision ID: 001
Revises:
Create Date: 2025-01-01
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

SCHEMA_NAME = "job_query_schema"

# Constants for server defaults
UUIDV7_DEFAULT = sa.text("uuidv7()")
NOW_DEFAULT = sa.func.now()
EMPTY_VARCHAR_ARRAY = sa.text("ARRAY[]::varchar[]")


def upgrade() -> None:
    """Create job_query_schema and tables."""
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

    op.create_table(
        "ingestion_queries",
        sa.Column("id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False),
        sa.Column("search_keywords", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("locations", postgresql.JSONB(), nullable=False),
        sa.Column(
            "work_arrangements",
            postgresql.ARRAY(work_arrangement_enum),
            nullable=False,
            server_default=sa.text("ARRAY[]::job_query_schema.work_arrangement_enum[]"),
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
            server_default=sa.text("ARRAY[]::job_query_schema.job_board_source_enum[]"),
        ),
        sa.Column("frequency", sa.Interval(), nullable=False, server_default=sa.text("'1 day'::interval")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active_contributor_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_contributor_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_recomputed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "search_keywords",
            "locations",
            name="uq_ingestion_queries_canonical",
        ),
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "query_contributors",
        sa.Column("query_id", postgresql.UUID(), nullable=False),
        sa.Column("pref_id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column(
            "work_arrangements",
            postgresql.ARRAY(work_arrangement_enum),
            nullable=False,
            server_default=sa.text("ARRAY[]::job_query_schema.work_arrangement_enum[]"),
        ),
        sa.Column("remote_preference", sa.String(20), nullable=False, server_default=sa.text("'any'")),
        sa.Column(
            "sources",
            postgresql.ARRAY(job_board_source_enum),
            nullable=False,
            server_default=sa.text("ARRAY[]::job_query_schema.job_board_source_enum[]"),
        ),
        sa.Column("frequency_tier", sa.String(10), nullable=False, server_default=sa.text("'daily'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.ForeignKeyConstraint(
            ["query_id"], [f"{SCHEMA_NAME}.ingestion_queries.id"], ondelete="CASCADE", name="fk_contributor_query"
        ),
        sa.PrimaryKeyConstraint("query_id", "pref_id"),
        sa.UniqueConstraint("pref_id", name="uq_query_contributors_pref_id"),
        schema=SCHEMA_NAME,
    )

    op.create_index("idx_contributors_user", "query_contributors", ["user_id"], schema=SCHEMA_NAME)
    op.create_index("idx_contributors_pref", "query_contributors", ["pref_id"], schema=SCHEMA_NAME)
    op.create_index("idx_queries_active", "ingestion_queries", ["is_active"], schema=SCHEMA_NAME)

    # Outbox table for CDC events (transactional outbox pattern)
    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False),
        sa.Column("aggregatetype", sa.String(255), nullable=False),
        sa.Column("aggregateid", sa.String(255), nullable=False),
        sa.Column("type", sa.String(255), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("tracingspancontext", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA_NAME,
    )

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop service tables and enum types."""
    op.drop_table("processed_events", schema=SCHEMA_NAME)
    op.drop_table("outbox", schema=SCHEMA_NAME)
    op.drop_table("query_contributors", schema=SCHEMA_NAME)
    op.drop_table("ingestion_queries", schema=SCHEMA_NAME)
    postgresql.ENUM(name="job_board_source_enum", schema=SCHEMA_NAME).drop(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM(name="work_arrangement_enum", schema=SCHEMA_NAME).drop(
        op.get_bind(), checkfirst=True
    )

"""
Initial migration for user-entitlement-service.

Schema: user_entitlement_schema
Tables: entitlements, outbox

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
from nohiki_db_utils.outbox_migrations import get_create_outbox_indexes_sql
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_NAME = "user_entitlement_schema"
UUIDV7_DEFAULT = sa.text("uuidv7()")
NOW_DEFAULT = sa.func.now()


def upgrade() -> None:
    """Create user_entitlement_schema and tables."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    subscription_tier_enum = postgresql.ENUM(
        "UNSPECIFIED", "FREE",
        "BASIC", "PRO", "ENTERPRISE",
        name="subscription_tier_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    subscription_tier_enum.create(op.get_bind(), checkfirst=True)

    subscription_status_enum = postgresql.ENUM(
        "UNSPECIFIED", "NONE",
        "TRIALING", "ACTIVE",
        "PAST_DUE", "CANCELED",
        "EXPIRED", "PAUSED",
        name="subscription_status_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    subscription_status_enum.create(op.get_bind(), checkfirst=True)

    billing_provider_enum = postgresql.ENUM(
        "UNSPECIFIED", "NONE",
        "STRIPE", "PADDLE", "MANUAL",
        name="billing_provider_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    billing_provider_enum.create(op.get_bind(), checkfirst=True)

    discovery_frequency_enum = postgresql.ENUM(
        "UNSPECIFIED", "DAILY",
        "TWICE_DAILY", "HOURLY", "REALTIME",
        name="discovery_frequency_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    discovery_frequency_enum.create(op.get_bind(), checkfirst=True)

    job_board_source_enum = postgresql.ENUM(
        "UNSPECIFIED", "INDEED",
        "LINKEDIN", "ZIPRECRUITER",
        "GOOGLE", "GLASSDOOR",
        "BAYT", "NAUKRI", "COMPANY_WEBSITE",
        name="job_board_source_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    job_board_source_enum.create(op.get_bind(), checkfirst=True)

    # Create entitlements table
    op.create_table(
        "entitlements",
        sa.Column(
            "id",
            postgresql.UUID(),
            server_default=UUIDV7_DEFAULT,
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column(
            "tier",
            subscription_tier_enum,
            server_default=sa.text("'FREE'"),
            nullable=False,
        ),
        sa.Column(
            "subscription_status",
            subscription_status_enum,
            server_default=sa.text("'NONE'"),
            nullable=False,
        ),
        sa.Column(
            "billing_provider",
            billing_provider_enum,
            server_default=sa.text("'NONE'"),
            nullable=False,
        ),
        sa.Column("external_subscription_id", sa.String(255), nullable=True),
        sa.Column("external_customer_id", sa.String(255), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "discovery_frequency_limit",
            discovery_frequency_enum,
            server_default=sa.text("'DAILY'"),
            nullable=False,
        ),
        sa.Column(
            "max_prefs",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "max_uploads_per_pref",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column(
            "allowed_sources",
            postgresql.ARRAY(job_board_source_enum),
            server_default=sa.text(
                "ARRAY['INDEED']"
                f"::{SCHEMA_NAME}.job_board_source_enum[]"
            ),
            nullable=False,
        ),
        sa.Column(
            "features_enabled",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        schema=SCHEMA_NAME,
    )

    # Create indexes
    op.create_index(
        "ix_entitlements_user",
        "entitlements",
        ["user_id"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_entitlements_tier",
        "entitlements",
        ["tier"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_entitlements_status",
        "entitlements",
        ["subscription_status"],
        schema=SCHEMA_NAME,
    )

    # Create outbox table for transactional outbox pattern (Debezium CDC)
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
    op.execute(get_create_outbox_indexes_sql(SCHEMA_NAME))

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop user_entitlement_schema schema."""
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")

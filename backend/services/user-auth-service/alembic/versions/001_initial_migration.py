"""
Initial migration for user-auth-service.

Schema: user_auth_schema
Tables: accounts, refresh_tokens, oauth_identities, outbox

Revision ID: 001
Revises:
Create Date: 2025-12-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from nohiki_db_utils.idempotency_migrations import (
    get_create_processed_events_index_sql,
    get_create_processed_events_sql,
)
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_NAME = "user_auth_schema"

# Constants for server defaults
UUIDV7_DEFAULT = sa.text("uuidv7()")
NOW_DEFAULT = sa.func.now()


def upgrade() -> None:
    """Create user_auth_schema and accounts table."""
    # Create schema
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    # Create CITEXT extension if not exists
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # Create accounts table
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        schema=SCHEMA_NAME,
    )

    # Create index on email
    op.create_index("ix_accounts_email", "accounts", ["email"], schema=SCHEMA_NAME)

    # Create refresh_tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False),
        sa.Column("account_id", postgresql.UUID(), nullable=False),
        sa.Column("token_id", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("session_family_id", postgresql.UUID(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], [f"{SCHEMA_NAME}.accounts.id"], ondelete="CASCADE"),
        schema=SCHEMA_NAME,
    )

    # Create indexes on refresh_tokens
    op.create_index("ix_refresh_tokens_account_id", "refresh_tokens", ["account_id"], schema=SCHEMA_NAME)
    op.create_index("ix_refresh_tokens_token_id", "refresh_tokens", ["token_id"], schema=SCHEMA_NAME)
    op.create_index("ix_refresh_tokens_session_family", "refresh_tokens", ["session_family_id"], schema=SCHEMA_NAME)
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"], schema=SCHEMA_NAME)

    # Create oauth_identities table - links external OAuth accounts to Nohiki accounts
    op.create_table(
        "oauth_identities",
        sa.Column("id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False),
        sa.Column("account_id", postgresql.UUID(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(255), nullable=True),
        sa.Column("provider_username", sa.String(255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_profile", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], [f"{SCHEMA_NAME}.accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        sa.UniqueConstraint("account_id", "provider", name="uq_oauth_account_provider"),
        schema=SCHEMA_NAME,
    )

    op.create_index("ix_oauth_identities_account_id", "oauth_identities", ["account_id"], schema=SCHEMA_NAME)
    op.create_index("ix_oauth_identities_provider", "oauth_identities", ["provider"], schema=SCHEMA_NAME)

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
    op.create_index(
        "ix_user_auth_schema_outbox_timestamp",
        "outbox",
        ["timestamp"],
        schema=SCHEMA_NAME,
    )

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop all application tables while preserving Alembic's version schema."""
    op.drop_table("processed_events", schema=SCHEMA_NAME)
    op.drop_table("outbox", schema=SCHEMA_NAME)
    op.drop_table("oauth_identities", schema=SCHEMA_NAME)
    op.drop_table("refresh_tokens", schema=SCHEMA_NAME)
    op.drop_table("accounts", schema=SCHEMA_NAME)

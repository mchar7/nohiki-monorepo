"""Initial migration for user-upload-service.

Schema: user_upload_schema
Tables: uploads, outbox

Revision ID: 001
Revises:
Create Date: 2024-12-13
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

SCHEMA_NAME = "user_upload_schema"

# Constants for server defaults (PostgreSQL 18+)
UUIDV7_DEFAULT = sa.text("uuidv7()")
NOW_DEFAULT = sa.func.now()


def upgrade() -> None:
    """Create user_upload_schema and uploads table."""
    # Create schema
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    # Create PostgreSQL ENUM types for document classification
    content_type_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "PDF",
        "DOCX",
        "DOC",
        "RTF",
        "TXT",
        "MARKDOWN",
        "HTML",
        "PNG",
        "JPEG",
        "WEBP",
        "JSON",
        name="content_type_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    content_type_enum.create(op.get_bind(), checkfirst=True)

    document_category_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "RESUME",
        "COVER_LETTER",
        "PORTFOLIO",
        "OTHER",
        name="document_category_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    document_category_enum.create(op.get_bind(), checkfirst=True)

    # Create uploads table
    op.create_table(
        "uploads",
        sa.Column("id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, primary_key=True),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "category",
            document_category_enum,
            nullable=False,
            server_default="UNSPECIFIED",
        ),
        sa.Column(
            "content_type",
            content_type_enum,
            nullable=False,
            server_default="UNSPECIFIED",
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        schema=SCHEMA_NAME,
    )

    # Create index on user_id
    op.create_index(
        "ix_uploads_user_id",
        "uploads",
        ["user_id"],
        schema=SCHEMA_NAME,
    )

    # Partial unique index: only non-deleted rows enforce uniqueness on (user_id, name)
    op.create_index(
        "ix_uploads_user_name_active",
        "uploads",
        ["user_id", "name"],
        unique=True,
        schema=SCHEMA_NAME,
        postgresql_where=sa.text("is_deleted = false"),
    )

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
    op.execute(get_create_outbox_indexes_sql(SCHEMA_NAME))

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop user_upload_schema schema."""
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")

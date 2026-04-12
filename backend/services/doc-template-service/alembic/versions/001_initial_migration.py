"""
Initial migration for doc-template-service.

Single-table design: Each row is a complete, immutable layout version.
Multiple versions of the same layout share (namespace, name, owner_id) but differ by version.

Revision ID: 001
Revises:
Create Date: 2025-07-08 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from nohiki_db_utils.idempotency_migrations import (
    get_create_processed_events_index_sql,
    get_create_processed_events_sql,
)
from nohiki_db_utils.outbox_migrations import (
    get_create_outbox_indexes_sql,
    get_create_outbox_table_sql,
)
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_NAME = "doc_template_schema"


def upgrade() -> None:
    """Create doc layout schema with single-table design."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    access_scope_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "PUBLIC",
        "PRIVATE",
        "SYSTEM",
        name="access_scope_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    access_scope_enum.create(op.get_bind(), checkfirst=True)

    template_audience_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "DOCUMENT",
        "INTERNAL",
        name="template_audience_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    template_audience_enum.create(op.get_bind(), checkfirst=True)

    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.document_templates (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            namespace VARCHAR(100) NOT NULL DEFAULT 'default',
            name VARCHAR(255) NOT NULL,
            display_name VARCHAR(255) NOT NULL,
            audience {SCHEMA_NAME}.template_audience_enum NOT NULL DEFAULT 'DOCUMENT',
            version VARCHAR(50) NOT NULL,
            template_content TEXT NOT NULL,
            content_schema JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            description TEXT,
            access_scope {SCHEMA_NAME}.access_scope_enum NOT NULL DEFAULT 'PUBLIC',
            owner_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            updated_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            last_used_at TIMESTAMPTZ,
            usage_count INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_template_name_version_owner UNIQUE NULLS NOT DISTINCT (namespace, name, version, owner_id),
            CONSTRAINT chk_version_semver CHECK (version ~ '^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)'
                '\\.(0|[1-9]\\d*)(-[0-9A-Za-z\\-\\.]+)?(\\+[0-9A-Za-z\\-\\.]+)?$'),
            CONSTRAINT chk_content_schema_json CHECK (content_schema IS JSON OBJECT)
        )
    """)

    op.execute(f"""
        CREATE INDEX ix_template_namespace_name_owner
        ON {SCHEMA_NAME}.document_templates (namespace, name, owner_id)
    """)

    op.execute(f"""
        CREATE INDEX ix_template_access_scope_owner
        ON {SCHEMA_NAME}.document_templates (access_scope, owner_id)
    """)

    op.execute(f"""
        CREATE INDEX ix_template_created
        ON {SCHEMA_NAME}.document_templates USING BRIN (created_at)
        WITH (pages_per_range = 32)
    """)

    op.execute(f"""
        COMMENT ON TABLE {SCHEMA_NAME}.document_templates IS
        'Document templates (single-table design: each row IS a version)'
    """)

    op.execute(get_create_outbox_table_sql(SCHEMA_NAME))
    op.execute(get_create_outbox_indexes_sql(SCHEMA_NAME))

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop all application-owned schema objects."""
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA_NAME}.processed_events")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA_NAME}.outbox")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA_NAME}.document_templates")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA_NAME}.template_audience_enum")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA_NAME}.access_scope_enum")

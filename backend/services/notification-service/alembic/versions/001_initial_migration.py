"""
Initial migration for notification-service.

Revision ID: 001
Revises:
Create Date: 2025-06-11 20:50:00.000000
"""

from collections.abc import Sequence

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

SCHEMA_NAME = "notification_schema"


def upgrade() -> None:
    """Create notification schema."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    notification_channel_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "EMAIL",
        "SMS",
        "PUSH_WEB",
        name="notification_channel_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    notification_channel_enum.create(op.get_bind(), checkfirst=True)

    msg_status_enum = postgresql.ENUM(
        "pending",
        "waiting_for_render",
        "sent",
        "failed",
        "retrying",
        "cancelled",
        name="msg_status_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    msg_status_enum.create(op.get_bind(), checkfirst=True)

    # Create messages table
    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.messages (
            id UUID PRIMARY KEY DEFAULT uuidv7(),

            -- References
            user_id UUID,
            correlation_id UUID,
            stored_listing_id UUID,

            -- Message details
            channel {SCHEMA_NAME}.notification_channel_enum NOT NULL,
            provider_name VARCHAR(255),
            status {SCHEMA_NAME}.msg_status_enum NOT NULL DEFAULT 'pending',
            external_layout_id UUID,
            external_layout_version VARCHAR(50),
            external_layout_content TEXT,
            recipient VARCHAR(255) NOT NULL,
            subject TEXT,
            body TEXT,
            template_vars JSONB,
            provider_payload JSONB,

            -- Processing
            retry_count INTEGER NOT NULL DEFAULT 0,
            priority SMALLINT NOT NULL DEFAULT 0,
            scheduled_at TIMESTAMPTZ,
            retry_at TIMESTAMPTZ,
            sent_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            last_error TEXT,
            provider_msg_id VARCHAR(255),

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- Constraints
            CONSTRAINT uq_messages_user_stored_job UNIQUE (user_id, stored_listing_id),
            CONSTRAINT chk_retry_count_range CHECK (retry_count >= 0 AND retry_count <= 10),
            CONSTRAINT chk_sent_at_consistency CHECK (
                (status = 'sent' AND sent_at IS NOT NULL) OR (status != 'sent')
            ),
            CONSTRAINT chk_priority_range CHECK (priority >= 0),
            CONSTRAINT chk_template_vars_json CHECK (
                template_vars IS NULL OR template_vars IS JSON OBJECT
            ),
            CONSTRAINT chk_provider_payload_json CHECK (
                provider_payload IS NULL OR provider_payload IS JSON OBJECT
            )
        )
    """)

    # BRIN index for time-series (messages are mostly append-only)
    op.execute(f"""
        CREATE INDEX ix_messages_created_at_brin
        ON {SCHEMA_NAME}.messages USING BRIN (created_at)
        WITH (pages_per_range = 32)
    """)

    # Hash index for status lookups
    op.execute(f"""
        CREATE INDEX ix_messages_status_hash
        ON {SCHEMA_NAME}.messages USING HASH (status)
    """)

    # Index for queue processing (pending messages ordered by priority)
    op.execute(f"""
        CREATE INDEX ix_messages_queue
        ON {SCHEMA_NAME}.messages (priority DESC, created_at)
        WHERE status IN ('pending', 'retrying')
    """)

    # Index for the TTL sweep; the predicate must stay identical to
    # ``MessageExpirySweep.build_expired_query`` or the sweep degrades to a scan
    op.execute(f"""
        CREATE INDEX ix_messages_expires_at
        ON {SCHEMA_NAME}.messages (expires_at)
        WHERE status IN ('pending', 'waiting_for_render', 'retrying') AND expires_at IS NOT NULL
    """)

    # Index for user message history
    op.execute(f"""
        CREATE INDEX ix_messages_user
        ON {SCHEMA_NAME}.messages (user_id, created_at DESC)
        WHERE user_id IS NOT NULL
    """)

    # Index for correlation lookups
    op.execute(f"""
        CREATE INDEX ix_messages_correlation_id
        ON {SCHEMA_NAME}.messages (correlation_id)
        WHERE correlation_id IS NOT NULL
    """)

    # Index for job-related messages
    op.execute(f"""
        CREATE INDEX ix_messages_stored_listing_id
        ON {SCHEMA_NAME}.messages (stored_listing_id)
        WHERE stored_listing_id IS NOT NULL
    """)

    op.execute(f"""
        COMMENT ON TABLE {SCHEMA_NAME}.messages IS
        'Notification messages'
    """)

    op.execute(get_create_outbox_table_sql(SCHEMA_NAME))
    op.execute(get_create_outbox_indexes_sql(SCHEMA_NAME))

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop notification schema."""
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")

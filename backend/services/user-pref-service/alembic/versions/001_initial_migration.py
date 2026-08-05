"""
Initial migration for user-pref-service.

Schema: user_pref_schema
Tables: search_prefs, search_pref_uploads, user_pref_settings, outbox

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
from nohiki_db_utils.outbox_migrations import (
    get_create_outbox_indexes_sql,
    get_create_outbox_table_sql,
)
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_NAME = "user_pref_schema"


def upgrade() -> None:
    """Create user_pref_schema and tables."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    work_arrangement_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "ON_SITE",
        "HYBRID",
        "REMOTE",
        name="work_arrangement_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    work_arrangement_enum.create(op.get_bind(), checkfirst=True)

    job_board_source_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "INDEED",
        "LINKEDIN",
        "ZIPRECRUITER",
        "GOOGLE",
        "GLASSDOOR",
        "BAYT",
        "NAUKRI",
        "COMPANY_WEBSITE",
        name="job_board_source_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    job_board_source_enum.create(op.get_bind(), checkfirst=True)

    seniority_level_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "INTERN",
        "ENTRY",
        "MID",
        "SENIOR",
        "STAFF",
        "MANAGER",
        "DIRECTOR",
        "VP",
        "EXECUTIVE",
        name="seniority_level_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    seniority_level_enum.create(op.get_bind(), checkfirst=True)

    s = SCHEMA_NAME
    op.execute(f"""
        CREATE TABLE {s}.search_prefs (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            user_id UUID NOT NULL,
            pref_name VARCHAR(100) NOT NULL,
            search_keywords VARCHAR(100)[] NOT NULL,
            disallowed_keywords VARCHAR(100)[] NOT NULL DEFAULT ARRAY[]::VARCHAR(100)[],
            physical_locations JSONB NOT NULL DEFAULT '[]'::jsonb,
            remote_locations JSONB NOT NULL DEFAULT '[]'::jsonb,
            open_to_relocation BOOLEAN NOT NULL DEFAULT false,
            commute_preferences JSONB,
            work_arrangements {s}.work_arrangement_enum[] NOT NULL,
            experience_years INTEGER,
            seniority_levels {s}.seniority_level_enum[] NOT NULL
                DEFAULT ARRAY[]::{s}.seniority_level_enum[],
            salary_preference JSONB,
            feature_importance JSONB,
            excluded_scrape_sources {s}.job_board_source_enum[] NOT NULL
                DEFAULT ARRAY[]::{s}.job_board_source_enum[],
            min_fit_score_disqualify INTEGER,
            auto_tailor_threshold INTEGER,
            tailoring_schema_id UUID,
            tailoring_preferences JSONB,
            notification_config JSONB,
            is_active BOOLEAN NOT NULL DEFAULT true,
            request_id UUID UNIQUE,
            user_skill_ids VARCHAR(100)[] DEFAULT ARRAY[]::VARCHAR(100)[],
            user_skills_data JSONB,
            semantic_content_generation INTEGER NOT NULL DEFAULT 0,
            semantic_content_hash VARCHAR(64),
            user_skills_embedding DOUBLE PRECISION[],
            query_embedding DOUBLE PRECISION[],
            query_artifacts_data JSONB,
            collection_version VARCHAR(10),
            enrichment_terminal_status VARCHAR(32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            updated_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()}
        )
    """)

    # Create search_pref_uploads junction table
    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.search_pref_uploads (
            pref_id UUID NOT NULL REFERENCES {SCHEMA_NAME}.search_prefs(id) ON DELETE CASCADE,
            upload_id UUID NOT NULL,
            upload_type VARCHAR(50) NOT NULL,
            PRIMARY KEY (pref_id, upload_id)
        )
    """)

    # Create indexes for search_prefs
    op.execute(f"CREATE INDEX ix_search_prefs_user_id ON {SCHEMA_NAME}.search_prefs (user_id)")
    op.execute(f"CREATE INDEX ix_search_prefs_request_id ON {SCHEMA_NAME}.search_prefs (request_id)")
    op.execute(f"CREATE INDEX ix_search_prefs_active ON {SCHEMA_NAME}.search_prefs (is_active) WHERE is_active = true")

    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.pref_enrichment_saga (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            expected_callbacks INTEGER NOT NULL,
            received_callbacks INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            pref_id UUID NOT NULL REFERENCES {SCHEMA_NAME}.search_prefs(id) ON DELETE CASCADE,
            user_id UUID NOT NULL,
            request_id UUID NOT NULL UNIQUE,
            action VARCHAR(16) NOT NULL,
            correlation_id VARCHAR(64) NOT NULL,
            raw_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
            last_dispatch_ids JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            skills_persisted BOOLEAN NOT NULL DEFAULT false,
            embedding_persisted BOOLEAN NOT NULL DEFAULT false,
            semantic_generation INTEGER NOT NULL,
            semantic_hash VARCHAR(64) NOT NULL,
            attempts_remaining INTEGER NOT NULL,
            failed_step VARCHAR(16),
            last_error_code VARCHAR(64),
            last_error_message VARCHAR(512),
            CONSTRAINT pref_enrichment_saga_status_check
                CHECK (status IN ('PENDING','COMPLETED','FAILED','EXPIRED','CANCELLED')),
            CONSTRAINT pref_enrichment_saga_expected_callbacks_positive CHECK (expected_callbacks > 0),
            CONSTRAINT pref_enrichment_saga_received_callbacks_nonnegative CHECK (received_callbacks >= 0),
            CONSTRAINT pref_enrichment_saga_version_positive CHECK (version > 0),
            CONSTRAINT pref_enrichment_saga_attempts_nonnegative CHECK (attempts_remaining >= 0)
        )
    """)
    op.execute(f"CREATE INDEX ix_pref_enrichment_saga_pref_id ON {SCHEMA_NAME}.pref_enrichment_saga (pref_id)")
    op.execute(
        f"CREATE UNIQUE INDEX uq_pref_enrichment_saga_pending_pref "
        f"ON {SCHEMA_NAME}.pref_enrichment_saga (pref_id) WHERE status = 'PENDING'"
    )
    op.execute(
        f"CREATE INDEX ix_pref_enrichment_saga_status_pending "
        f"ON {SCHEMA_NAME}.pref_enrichment_saga (status) WHERE status = 'PENDING'"
    )
    op.execute(
        f"CREATE INDEX ix_pref_enrichment_saga_expires "
        f"ON {SCHEMA_NAME}.pref_enrichment_saga (expires_at) WHERE status = 'PENDING'"
    )
    # Create user_pref_settings table for user-level preference defaults
    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.user_pref_settings (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            user_id UUID NOT NULL UNIQUE,
            default_feature_importance JSONB,
            preferred_timezone VARCHAR(50),
            preferred_locale VARCHAR(10),
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            updated_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()}
        )
    """)

    # Create index for user_pref_settings
    op.execute(f"CREATE INDEX ix_user_pref_settings_user_id ON {SCHEMA_NAME}.user_pref_settings (user_id)")

    op.execute(get_create_outbox_table_sql(SCHEMA_NAME))
    op.execute(get_create_outbox_indexes_sql(SCHEMA_NAME))

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop user_pref_schema schema."""
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")

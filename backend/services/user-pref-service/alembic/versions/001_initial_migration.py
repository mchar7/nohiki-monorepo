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
            is_enrichment_complete BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            updated_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            CONSTRAINT chk_search_keywords_nonempty CHECK (cardinality(search_keywords) > 0),
            CONSTRAINT chk_work_arrangements_nonempty CHECK (cardinality(work_arrangements) > 0)
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

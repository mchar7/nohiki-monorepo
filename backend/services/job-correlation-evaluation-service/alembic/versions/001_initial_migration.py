"""Initial migration for job-correlation-evaluation-service.

Schema: job_correlation_schema
Tables: correlations, profile_projections

Schema: feedback
Tables: asymmetric_feedback, manual_adjustments

Revision ID: 001
Revises:
Create Date: 2025-12-14
"""

from collections.abc import Sequence

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

SCHEMA_NAME = "job_correlation_schema"
_GRANT_EMIT_EXECUTE_SQL = """
DO $wal_emit$
BEGIN
    BEGIN
        REVOKE EXECUTE ON FUNCTION pg_catalog.pg_logical_emit_message(boolean, text, bytea) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION pg_catalog.pg_logical_emit_message(boolean, text, bytea) TO CURRENT_USER;
    EXCEPTION WHEN undefined_function THEN NULL;
    END;
    BEGIN
        REVOKE EXECUTE ON FUNCTION pg_catalog.pg_logical_emit_message(boolean, text, bytea, boolean) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION pg_catalog.pg_logical_emit_message(boolean, text, bytea, boolean) TO CURRENT_USER;
    EXCEPTION WHEN undefined_function THEN NULL;
    END;
END
$wal_emit$;
"""


def upgrade() -> None:
    """Create job correlation schema."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    correlation_status_enum = postgresql.ENUM(
        "pending",
        "evaluated",
        "viewed",
        "saved",
        "applied",
        "dismissed",
        "expired",
        name="correlation_status_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    correlation_status_enum.create(op.get_bind(), checkfirst=True)

    user_feedback_enum = postgresql.ENUM(
        "liked",
        "disliked",
        "saved",
        "interested",
        name="user_feedback_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    user_feedback_enum.create(op.get_bind(), checkfirst=True)

    # Create correlations table
    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.correlations (
            id UUID PRIMARY KEY DEFAULT uuidv7(),

            -- References (logical FKs - NOT ENFORCED for cross-schema)
            pref_id UUID NOT NULL,
            listing_id UUID NOT NULL,
            user_id UUID NOT NULL,
            listing_url TEXT NOT NULL,

            -- Correlation data
            correlation_score INTEGER,
            correlation_reasoning JSONB,
            correlation_status {SCHEMA_NAME}.correlation_status_enum NOT NULL DEFAULT 'pending',
            user_feedback {SCHEMA_NAME}.user_feedback_enum,

            -- Interaction flags
            is_viewed BOOLEAN NOT NULL DEFAULT false,
            is_applied BOOLEAN NOT NULL DEFAULT false,
            is_dismissed BOOLEAN NOT NULL DEFAULT false,

            -- ML Training data
            feature_vector FLOAT[] DEFAULT NULL,
            feature_schema_version VARCHAR(16) NOT NULL,

            -- Stored generated column for actionable status
            -- Note: VIRTUAL not supported with user-defined types (enums) in PostgreSQL 18
            is_actionable BOOLEAN GENERATED ALWAYS AS (
                correlation_status IN ('evaluated', 'pending') AND is_dismissed = false
            ) STORED,

            -- Timestamps
            evaluated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- Constraints
            CONSTRAINT uq_correlation_pref_listing UNIQUE (pref_id, listing_id),
            CONSTRAINT chk_score_range CHECK (
                correlation_score IS NULL OR (correlation_score >= 0 AND correlation_score <= 100)
            )
        )
    """)

    # Note: No cross-schema FKs per EDA best practices.
    # Listing and pref deletions are handled via event-driven eventual consistency:
    # - job-listing.cdc.listing-deleted.v1 -> invalidates correlations for deleted listings
    # - user-pref.cdc.pref-deleted.v1 -> invalidates correlations for deleted prefs

    # Hash index for status (equality lookups)
    op.execute(f"""
        CREATE INDEX idx_correlations_status_hash
        ON {SCHEMA_NAME}.correlations USING HASH (correlation_status)
    """)

    # BRIN for time columns
    op.execute(f"""
        CREATE INDEX idx_correlations_created_at_brin
        ON {SCHEMA_NAME}.correlations USING BRIN (created_at)
        WITH (pages_per_range = 32)
    """)

    # Composite index for pref queries with ordering
    op.execute(f"""
        CREATE INDEX idx_correlations_pref_score
        ON {SCHEMA_NAME}.correlations (pref_id, correlation_score DESC NULLS LAST)
    """)

    # Partial index for actionable correlations
    op.execute(f"""
        CREATE INDEX idx_correlations_actionable
        ON {SCHEMA_NAME}.correlations (pref_id, evaluated_at DESC)
        WHERE correlation_status IN ('evaluated', 'pending') AND is_dismissed = false
    """)

    # Index for listing lookups
    op.execute(f"""
        CREATE INDEX idx_correlations_listing_id
        ON {SCHEMA_NAME}.correlations (listing_id)
    """)

    # Index for user lookups
    op.execute(f"""
        CREATE INDEX idx_correlations_user_id
        ON {SCHEMA_NAME}.correlations (user_id)
    """)

    op.execute(f"""
        COMMENT ON TABLE {SCHEMA_NAME}.correlations IS
        'Listing-user correlations with UUIDv7, virtual generated columns. Uses EDA for cross-service consistency.'
    """)

    # =========================================================================
    # Profile Projections Table
    # Populated by: pref.created.v1, pref.updated.v1, pref.deleted.v1
    # Purpose: Provides all active profiles for job matching
    # =========================================================================
    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.profile_projections (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL,
            profile_name VARCHAR(255) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            source_revision TIMESTAMPTZ NOT NULL,
            snapshot_data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute(f"""
        CREATE INDEX ix_profile_projections_user_id
        ON {SCHEMA_NAME}.profile_projections (user_id)
    """)

    op.execute(f"""
        CREATE INDEX ix_profile_projections_is_active
        ON {SCHEMA_NAME}.profile_projections (is_active)
        WHERE is_active = true
    """)

    op.execute(f"""
        COMMENT ON TABLE {SCHEMA_NAME}.profile_projections IS
        'Profile projections populated via ECST events from user-pref-service. Used for job matching.'
    """)

    # =========================================================================
    # Feedback Schema
    # Tables for L2R feedback collection and model improvement
    # =========================================================================
    op.execute("CREATE SCHEMA IF NOT EXISTS feedback")

    # Asymmetric feedback table - captures GOOD/TOO_HIGH/TOO_LOW signals
    op.execute("""
        CREATE TABLE IF NOT EXISTS feedback.asymmetric_feedback (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            correlation_id UUID NOT NULL,
            user_id UUID NOT NULL,
            feedback_type VARCHAR(16) NOT NULL CHECK (feedback_type IN ('GOOD', 'TOO_HIGH', 'TOO_LOW')),
            request_id VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_asymmetric_feedback_request_id UNIQUE (request_id)
        )
    """)

    op.execute("""
        CREATE INDEX ix_asymmetric_feedback_correlation_id
        ON feedback.asymmetric_feedback (correlation_id)
    """)

    op.execute("""
        CREATE INDEX ix_asymmetric_feedback_user_id
        ON feedback.asymmetric_feedback (user_id)
    """)

    op.execute("""
        CREATE INDEX ix_asymmetric_feedback_created_at_brin
        ON feedback.asymmetric_feedback USING BRIN (created_at)
        WITH (pages_per_range = 32)
    """)

    op.execute("""
        COMMENT ON TABLE feedback.asymmetric_feedback IS
        'Asymmetric feedback on correlation scores. feedback_type: GOOD, TOO_HIGH, TOO_LOW (proto enum names)'
    """)

    # Manual adjustments table - user-provided score overrides with reasoning
    op.execute("""
        CREATE TABLE IF NOT EXISTS feedback.manual_adjustments (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            correlation_id UUID NOT NULL,
            user_id UUID NOT NULL,
            original_score DOUBLE PRECISION NOT NULL,
            adjusted_score DOUBLE PRECISION NOT NULL,
            reasoning TEXT NOT NULL,
            request_id VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_manual_adjustment_request_id UNIQUE (request_id),
            CONSTRAINT ck_manual_adjustment_original_score_range
                CHECK (original_score >= 0.0 AND original_score <= 1.0),
            CONSTRAINT ck_manual_adjustment_adjusted_score_range
                CHECK (adjusted_score >= 0.0 AND adjusted_score <= 1.0)
        )
    """)

    op.execute("""
        CREATE INDEX ix_manual_adjustments_correlation_id
        ON feedback.manual_adjustments (correlation_id)
    """)

    op.execute("""
        CREATE INDEX ix_manual_adjustments_user_id
        ON feedback.manual_adjustments (user_id)
    """)

    op.execute("""
        CREATE INDEX ix_manual_adjustments_created_at_brin
        ON feedback.manual_adjustments USING BRIN (created_at)
        WITH (pages_per_range = 32)
    """)

    op.execute("""
        COMMENT ON TABLE feedback.manual_adjustments IS
        'Manual score adjustments with user-provided reasoning. Scores are DOUBLE PRECISION (0.0-1.0).'
    """)

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))
    op.execute(_GRANT_EMIT_EXECUTE_SQL)


def downgrade() -> None:
    """Drop all service-owned database objects."""
    op.execute("DROP SCHEMA IF EXISTS feedback CASCADE")
    op.execute(f"""
        DO $$
        DECLARE
            table_name TEXT;
        BEGIN
            FOR table_name IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = '{SCHEMA_NAME}'
                  AND tablename <> 'alembic_version'
            LOOP
                EXECUTE format('DROP TABLE {SCHEMA_NAME}.%I CASCADE', table_name);
            END LOOP;
        END
        $$
    """)
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA_NAME}.correlation_status_enum CASCADE")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA_NAME}.user_feedback_enum CASCADE")

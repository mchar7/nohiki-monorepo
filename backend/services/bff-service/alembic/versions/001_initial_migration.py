"""Initial migration for bff_schema projections."""

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

UUIDV7_DEFAULT = sa.text("uuidv7()")
NOW_DEFAULT = sa.func.now()
EMPTY_ARRAY_DEFAULT = sa.text("'{}'")
PENDING_DEFAULT = sa.text("'pending'")
SCHEMA_NAME = "bff_schema"


def _create_job_listing_search_trigger() -> None:
    """Create trigger function and trigger for job listing FTS updates."""
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.job_listing_search_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(NEW.company_name, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(array_to_string(NEW.required_skills, ' '), '')), 'B') ||
                setweight(to_tsvector('english', coalesce(NEW.description, '')), 'C');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute(f"""
        CREATE TRIGGER job_listing_search_update
        BEFORE INSERT OR UPDATE ON {SCHEMA_NAME}.job_listing_projections
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA_NAME}.job_listing_search_trigger();
    """)


def _drop_job_listing_search_trigger() -> None:
    """Drop trigger and trigger function for job listing FTS."""
    op.execute(
        f"DROP TRIGGER IF EXISTS job_listing_search_update ON {SCHEMA_NAME}.job_listing_projections"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA_NAME}.job_listing_search_trigger()")


def _create_skill_search_trigger() -> None:
    """Create trigger function and trigger for skill FTS updates."""
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.skill_search_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', coalesce(NEW.normalized_text, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(NEW.display_name, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(NEW.category, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(NEW.description, '')), 'C');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute(f"""
        CREATE TRIGGER skill_search_update
        BEFORE INSERT OR UPDATE ON {SCHEMA_NAME}.skill_projections
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA_NAME}.skill_search_trigger();
    """)


def _drop_skill_search_trigger() -> None:
    """Drop trigger and trigger function for skill FTS."""
    op.execute(
        f"DROP TRIGGER IF EXISTS skill_search_update ON {SCHEMA_NAME}.skill_projections"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA_NAME}.skill_search_trigger()")


def upgrade() -> None:
    """Create bff_schema and all projection tables."""
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

    op.create_table(
        "revoked_access_tokens",
        sa.Column("jti", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_revoked_access_tokens_expires_at",
        "revoked_access_tokens",
        ["expires_at"],
        schema=SCHEMA_NAME,
    )
    op.create_table(
        "user_revocation_cutoffs",
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("revoked_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_permanent", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_user_revocation_cutoffs_expires_at",
        "user_revocation_cutoffs",
        ["expires_at"],
        schema=SCHEMA_NAME,
    )
    op.create_table(
        "revoked_session_families",
        sa.Column("family_id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("revoked_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("family_id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_revoked_session_families_expires_at",
        "revoked_session_families",
        ["expires_at"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "account_projections",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "profile_projections",
        sa.Column(
            "id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("profile_name", sa.String(100), nullable=False),
        sa.Column(
            "search_keywords",
            postgresql.ARRAY(sa.String()),
            server_default=EMPTY_ARRAY_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "disallowed_keywords",
            postgresql.ARRAY(sa.String()),
            server_default=EMPTY_ARRAY_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "user_skills",
            postgresql.ARRAY(sa.String()),
            server_default=EMPTY_ARRAY_DEFAULT,
            nullable=False,
        ),
        sa.Column(
            "work_arrangements",
            postgresql.ARRAY(
                postgresql.ENUM(
                    "UNSPECIFIED",
                    "ON_SITE",
                    "HYBRID",
                    "REMOTE",
                    name="work_arrangement_enum",
                    schema=SCHEMA_NAME,
                    create_type=False,
                )
            ),
            server_default=sa.text(f"ARRAY[]::{SCHEMA_NAME}.work_arrangement_enum[]"),
            nullable=False,
        ),
        sa.Column(
            "notification_threshold",
            sa.Float(),
            server_default=sa.text("0.70"),
            nullable=False,
        ),
        sa.Column("auto_tailor_threshold", sa.Float(), nullable=True),
        sa.Column("tailoring_schema_id", postgresql.UUID(), nullable=True),
        sa.Column("feature_importance", postgresql.JSONB(), nullable=True),
        sa.Column(
            "open_to_relocation",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("commute_preferences", postgresql.JSONB(), nullable=True),
        sa.Column("salary_preference", postgresql.JSONB(), nullable=True),
        sa.Column("experience_preference", postgresql.JSONB(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
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
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_profile_projections_user_id",
        "profile_projections",
        ["user_id"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "user_pref_settings_projections",
        sa.Column(
            "id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(), nullable=False, unique=True),
        sa.Column("default_feature_importance", postgresql.JSONB(), nullable=True),
        sa.Column("preferred_timezone", sa.String(50), nullable=True),
        sa.Column("preferred_locale", sa.String(10), nullable=True),
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
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_user_pref_settings_projections_user_id",
        "user_pref_settings_projections",
        ["user_id"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "attachment_projections",
        sa.Column(
            "id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_attachment_projections_user_id",
        "attachment_projections",
        ["user_id"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "schema_family_projections",
        sa.Column(
            "id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False
        ),
        sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
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
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_schema_family_projections_namespace",
        "schema_family_projections",
        ["namespace"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "schema_version_projections",
        sa.Column(
            "id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False
        ),
        sa.Column("family_id", postgresql.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_content", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_schema_version_projections_family_id",
        "schema_version_projections",
        ["family_id"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "template_projections",
        sa.Column(
            "id", postgresql.UUID(), server_default=UUIDV7_DEFAULT, nullable=False
        ),
        sa.Column("version_id", postgresql.UUID(), nullable=True),
        sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("template_content", sa.Text(), nullable=False),
        sa.Column("content_schema", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "access_scope",
            postgresql.ENUM(
                "UNSPECIFIED",
                "PUBLIC",
                "PRIVATE",
                "SYSTEM",
                name="access_scope_enum",
                schema=SCHEMA_NAME,
                create_type=False,
            ),
            server_default=sa.text("'PUBLIC'"),
            nullable=False,
        ),
        sa.Column(
            "audience",
            postgresql.ENUM(
                "UNSPECIFIED",
                "DOCUMENT",
                "INTERNAL",
                name="template_audience_enum",
                schema=SCHEMA_NAME,
                create_type=False,
            ),
            server_default=sa.text("'DOCUMENT'"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_template_projections_namespace_name",
        "template_projections",
        ["namespace", "name"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_template_projections_created_at",
        "template_projections",
        ["created_at"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "document_generation_status",
        sa.Column("request_id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("job_correlation_id", postgresql.UUID(), nullable=True),
        sa.Column("pref_id", postgresql.UUID(), nullable=True),
        sa.Column("listing_id", postgresql.UUID(), nullable=True),
        sa.Column("template_version_id", postgresql.UUID(), nullable=False),
        sa.Column("output_format", sa.String(10), nullable=False),
        sa.Column(
            "status", sa.String(20), server_default=PENDING_DEFAULT, nullable=False
        ),
        sa.Column("storage_key", sa.String(512), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("request_id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_document_generation_status_user_id",
        "document_generation_status",
        ["user_id"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "command_requests",
        sa.Column(
            "request_id",
            postgresql.UUID(),
            server_default=UUIDV7_DEFAULT,
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("command_type", sa.String(50), nullable=False),
        sa.Column(
            "status", sa.String(20), server_default=PENDING_DEFAULT, nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("request_id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_command_requests_user_id",
        "command_requests",
        ["user_id"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "job_listing_projections",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("listing_url", sa.String(2048), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("company_name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location_raw", sa.String(500), nullable=False),
        sa.Column("work_arrangement", sa.String(50), nullable=True),
        sa.Column("seniority_level", sa.String(50), nullable=True),
        sa.Column("language", sa.String(5), nullable=True),
        sa.Column(
            "required_skills",
            postgresql.ARRAY(sa.String()),
            server_default=EMPTY_ARRAY_DEFAULT,
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("raw_content_hash", sa.String(64), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW_DEFAULT,
            nullable=False,
        ),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("salary_min", sa.BigInteger(), nullable=True),
        sa.Column("salary_max", sa.BigInteger(), nullable=True),
        sa.Column("salary_currency", sa.String(10), nullable=True),
        sa.Column("salary_frequency", sa.String(20), nullable=True),
        sa.Column("company_logo_url", sa.String(2048), nullable=True),
        sa.Column("experience_years_min", sa.Integer(), nullable=True),
        sa.Column("experience_years_max", sa.Integer(), nullable=True),
        sa.Column("country_code", sa.String(3), nullable=True),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_job_listing_projections_company",
        "job_listing_projections",
        ["company_name"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_job_listing_projections_created_at",
        "job_listing_projections",
        ["created_at"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_job_listing_projections_language",
        "job_listing_projections",
        ["language"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_job_listing_projections_search",
        "job_listing_projections",
        ["search_vector"],
        schema=SCHEMA_NAME,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_job_listing_projections_country_code",
        "job_listing_projections",
        ["country_code"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_job_listing_projections_country_posted",
        "job_listing_projections",
        ["country_code", "posted_at"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_job_listing_projections_posted_at",
        "job_listing_projections",
        ["posted_at"],
        schema=SCHEMA_NAME,
    )
    _create_job_listing_search_trigger()

    op.create_table(
        "job_correlation_projections",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("pref_id", postgresql.UUID(), nullable=False),
        sa.Column("listing_id", postgresql.UUID(), nullable=False),
        sa.Column("fit_score", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(30), server_default=PENDING_DEFAULT, nullable=False
        ),
        sa.Column(
            "score_breakdown",
            postgresql.JSONB(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("fit_ranking_breakdown", postgresql.JSONB(), nullable=True),
        sa.Column("pref_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("pref_uploads", postgresql.JSONB(), nullable=True),
        sa.Column("listing_title", sa.String(500), nullable=False),
        sa.Column("listing_company", sa.String(500), nullable=True),
        sa.Column("listing_url", sa.String(2048), nullable=False),
        sa.Column("listing_location", sa.String(500), nullable=True),
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
        sa.UniqueConstraint(
            "pref_id", "listing_id", name="uq_correlation_pref_listing"
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_job_correlation_projections_user_id",
        "job_correlation_projections",
        ["user_id"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_job_correlation_projections_pref_id",
        "job_correlation_projections",
        ["pref_id"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_job_correlation_projections_fit_score",
        "job_correlation_projections",
        ["fit_score"],
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "skill_projections",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("canonical_id", sa.String(150), nullable=False, unique=True),
        sa.Column("normalized_text", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(200), nullable=True),
        sa.Column("subcategory", sa.String(200), nullable=True),
        sa.Column("skill_type", sa.String(20), nullable=True),
        sa.Column("reuse_level", sa.String(25), nullable=True),
        sa.Column(
            "source", sa.String(20), server_default=sa.text("'TABIYA'"), nullable=False
        ),
        sa.Column(
            "mention_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "job_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "profile_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
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
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_skill_projections_normalized_text",
        "skill_projections",
        ["normalized_text"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_skill_projections_category",
        "skill_projections",
        ["category"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_skill_projections_search",
        "skill_projections",
        ["search_vector"],
        schema=SCHEMA_NAME,
        postgresql_using="gin",
    )
    _create_skill_search_trigger()
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_skill_projections_normalized_text_lower_prefix "
        f"ON {SCHEMA_NAME}.skill_projections (lower(normalized_text) text_pattern_ops)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_skill_projections_preferred_label_lower_prefix "
        f"ON {SCHEMA_NAME}.skill_projections "
        "(lower(coalesce(display_name, normalized_text)) text_pattern_ops)"
    )

    op.execute(get_create_outbox_table_sql(SCHEMA_NAME))
    op.execute(get_create_outbox_indexes_sql(SCHEMA_NAME))

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop all BFF-owned tables while Alembic retains its version table schema."""
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA_NAME}.processed_events")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA_NAME}.outbox")
    op.drop_table("job_correlation_projections", schema=SCHEMA_NAME)
    _drop_job_listing_search_trigger()
    op.drop_table("job_listing_projections", schema=SCHEMA_NAME)
    _drop_skill_search_trigger()
    op.drop_table("skill_projections", schema=SCHEMA_NAME)
    op.drop_table("command_requests", schema=SCHEMA_NAME)
    op.drop_table("document_generation_status", schema=SCHEMA_NAME)
    op.drop_table("template_projections", schema=SCHEMA_NAME)
    op.drop_table("schema_version_projections", schema=SCHEMA_NAME)
    op.drop_table("schema_family_projections", schema=SCHEMA_NAME)
    op.drop_table("attachment_projections", schema=SCHEMA_NAME)
    op.drop_table("user_pref_settings_projections", schema=SCHEMA_NAME)
    op.drop_table("profile_projections", schema=SCHEMA_NAME)
    op.drop_table("account_projections", schema=SCHEMA_NAME)
    op.drop_table("revoked_session_families", schema=SCHEMA_NAME)
    op.drop_table("user_revocation_cutoffs", schema=SCHEMA_NAME)
    op.drop_table("revoked_access_tokens", schema=SCHEMA_NAME)

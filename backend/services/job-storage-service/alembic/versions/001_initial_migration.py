"""
Initial migration for job-storage-service.

Schema: job_storage_schema
Tables: listings

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
from nohiki_db_utils.outbox_migrations import (
    get_create_outbox_indexes_sql,
    get_create_outbox_table_sql,
)
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_NAME = "job_storage_schema"


def upgrade() -> None:
    """Create job storage schema."""
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

    employment_term_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "FULL_TIME",
        "PART_TIME",
        "CONTRACT",
        "INTERNSHIP",
        "TEMPORARY",
        "SEASONAL",
        name="employment_term_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    employment_term_enum.create(op.get_bind(), checkfirst=True)

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

    listing_status_enum = postgresql.ENUM(
        "UNSPECIFIED",
        "ACTIVE",
        "STALE",
        "EXPIRED",
        name="listing_status_enum",
        schema=SCHEMA_NAME,
        create_type=False,
    )
    listing_status_enum.create(op.get_bind(), checkfirst=True)

    # Create main listings table
    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.listings (
            id UUID PRIMARY KEY DEFAULT uuidv7(),

            -- Identification
            listing_url TEXT NOT NULL,
            job_board_source {SCHEMA_NAME}.job_board_source_enum NOT NULL,
            external_id VARCHAR(255),

            -- Core details
            title VARCHAR(500) NOT NULL,
            company_name VARCHAR(500) NOT NULL,
            description TEXT NOT NULL,
            company_logo_url VARCHAR(2048),

            -- Location (structured form populated during enrichment)
            location JSONB NOT NULL,

            -- Classification
            work_arrangement {SCHEMA_NAME}.work_arrangement_enum NOT NULL DEFAULT 'UNSPECIFIED',
            employment_term {SCHEMA_NAME}.employment_term_enum NOT NULL DEFAULT 'UNSPECIFIED',
            seniority_level {SCHEMA_NAME}.seniority_level_enum NOT NULL DEFAULT 'UNSPECIFIED',
            language VARCHAR(5) NOT NULL DEFAULT 'und',

            -- Requirements
            required_skills TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            min_experience_years INTEGER,
            max_experience_years INTEGER,

            -- Canonical skill IDs from skill-graph-service
            canonical_skill_ids TEXT[],

            -- Pre-computed embeddings for semantic matching
            skills_embedding FLOAT8[],
            title_embedding FLOAT8[],

            -- Collection version for embedding compatibility tracking
            collection_version VARCHAR(10),

            -- Compensation (raw from scrape)
            compensation JSONB,

            -- Status & versioning
            status {SCHEMA_NAME}.listing_status_enum NOT NULL DEFAULT 'ACTIVE',
            version INTEGER NOT NULL DEFAULT 1,

            -- Content change detection (SHA-256 hash of raw listing data)
            raw_content_hash VARCHAR(64) NOT NULL,

            -- Cross-source deduplication hash
            -- SHA-256 of normalized: lowercase(title) + lowercase(company_name) + date(posted_at)
            dedup_hash VARCHAR(64) NOT NULL,

            -- Full-text search vector (populated by trigger)
            search_vector TSVECTOR,

            -- Timestamps
            posted_at TIMESTAMPTZ,
            discovered_at TIMESTAMPTZ NOT NULL,
            processed_at TIMESTAMPTZ,
            processing_correlation_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- JSONB validation: location is required and must be a JSON object
            CONSTRAINT chk_location_json CHECK (
                location IS JSON OBJECT
            ),
            CONSTRAINT chk_compensation_json CHECK (
                compensation IS NULL OR compensation IS JSON
            ),

            -- Business constraints
            CONSTRAINT chk_experience_range CHECK (
                min_experience_years IS NULL OR max_experience_years IS NULL OR
                min_experience_years <= max_experience_years
            ),
            CONSTRAINT chk_company_name_length CHECK (
                length(company_name) >= 1
            ),
            CONSTRAINT chk_description_length CHECK (
                length(description) >= 200
            )
        )
    """)

    # Create indexes
    # listing_url uniqueness: a single canonical row per URL. Cross-source
    # variants are merged via dedup_hash before this constraint is hit, and
    # in-flight ingests are gated by the partial unique index on
    # listing_ingest_saga (PENDING) so duplicate concurrent inserts cannot
    # reach this table.
    op.execute(f"""
        CREATE UNIQUE INDEX ix_listings_url
        ON {SCHEMA_NAME}.listings (listing_url)
    """)

    # GIN index for full-text search
    op.execute(f"""
        CREATE INDEX ix_listings_search_vector
        ON {SCHEMA_NAME}.listings USING GIN (search_vector)
    """)

    # BRIN index for time-series data (100x smaller than B-tree)
    op.execute(f"""
        CREATE INDEX ix_listings_discovered_at_brin
        ON {SCHEMA_NAME}.listings USING BRIN (discovered_at)
        WITH (pages_per_range = 32)
    """)

    op.execute(f"""
        CREATE INDEX ix_listings_created_at_brin
        ON {SCHEMA_NAME}.listings USING BRIN (created_at)
        WITH (pages_per_range = 32)
    """)

    # Hash index for equality-only lookups
    op.execute(f"""
        CREATE INDEX ix_listings_source_hash
        ON {SCHEMA_NAME}.listings USING HASH (job_board_source)
    """)

    # GIN index for JSONB containment queries
    op.execute(f"""
        CREATE INDEX ix_listings_location_gin
        ON {SCHEMA_NAME}.listings USING GIN (location jsonb_path_ops)
    """)

    # GIN index for array containment
    op.execute(f"""
        CREATE INDEX ix_listings_skills_gin
        ON {SCHEMA_NAME}.listings USING GIN (required_skills)
    """)

    # B-tree indexes for common queries
    op.execute(f"""
        CREATE INDEX ix_listings_company_name
        ON {SCHEMA_NAME}.listings (company_name)
    """)

    op.execute(f"""
        CREATE INDEX ix_listings_work_arrangement
        ON {SCHEMA_NAME}.listings (work_arrangement)
    """)

    op.execute(f"""
        CREATE INDEX ix_listings_language
        ON {SCHEMA_NAME}.listings (language)
    """)

    op.execute(f"""
        CREATE INDEX ix_listings_active
        ON {SCHEMA_NAME}.listings (created_at DESC)
        WHERE status = 'ACTIVE'
    """)

    # Unique index for cross-source content deduplication
    # Uses dedup_hash which is source-agnostic
    op.execute(f"""
        CREATE UNIQUE INDEX ix_listings_dedup
        ON {SCHEMA_NAME}.listings (dedup_hash)
    """)

    # Index for content hash lookups (change detection)
    op.execute(f"""
        CREATE INDEX ix_listings_content_hash
        ON {SCHEMA_NAME}.listings (raw_content_hash)
    """)

    # Create trigger function for search_vector
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.listings_search_vector_update()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(NEW.company_name, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(NEW.description, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(array_to_string(NEW.required_skills, ' '), '')), 'B');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger
    op.execute(f"""
        CREATE TRIGGER trg_listings_search_vector_update
        BEFORE INSERT OR UPDATE ON {SCHEMA_NAME}.listings
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA_NAME}.listings_search_vector_update();
    """)

    # Add table comment
    op.execute(f"""
        COMMENT ON TABLE {SCHEMA_NAME}.listings IS
        'Canonical job listings with UUIDv7, TSVECTOR FTS, BRIN indexes'
    """)

    # Create listing_versions table for version history tracking
    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.listing_versions (
            id UUID PRIMARY KEY DEFAULT uuidv7(),

            -- Reference to the parent listing
            listing_id UUID NOT NULL REFERENCES {SCHEMA_NAME}.listings(id) ON DELETE CASCADE,

            -- Version number at the time of this snapshot
            version INTEGER NOT NULL,

            -- Content hash at the time of this version
            raw_content_hash VARCHAR(64) NOT NULL,

            -- Full snapshot of the listing state at this version (JSONB)
            snapshot JSONB NOT NULL,

            -- Change metadata
            change_type VARCHAR(20) NOT NULL,  -- 'created', 'updated', 'enriched'
            change_reason TEXT,                -- Optional description of what changed

            -- Processing context
            correlation_id VARCHAR(255),

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            -- Constraints
            CONSTRAINT chk_change_type CHECK (
                change_type IN ('created', 'updated', 'enriched')
            ),
            CONSTRAINT chk_version_positive CHECK (version > 0)
        )
    """)

    # Indexes for listing_versions
    op.execute(f"""
        CREATE INDEX ix_listing_versions_listing_id
        ON {SCHEMA_NAME}.listing_versions (listing_id)
    """)

    op.execute(f"""
        CREATE INDEX ix_listing_versions_listing_version
        ON {SCHEMA_NAME}.listing_versions (listing_id, version DESC)
    """)

    op.execute(f"""
        CREATE INDEX ix_listing_versions_created_at_brin
        ON {SCHEMA_NAME}.listing_versions USING BRIN (created_at)
        WITH (pages_per_range = 32)
    """)

    # Add table comment
    op.execute(f"""
        COMMENT ON TABLE {SCHEMA_NAME}.listing_versions IS
        'Version history for job listings, storing full snapshots for audit and change tracking'
    """)

    # In-flight ingest saga: discovered listings awaiting enrichment.
    # Pre-enrichment state cannot satisfy listings.NOT_NULL on description/location,
    # so this table holds the row until EnrichmentCompleted promotes it to listings.
    op.execute(f"""
        CREATE TABLE {SCHEMA_NAME}.listing_ingest_saga (
            id UUID PRIMARY KEY DEFAULT uuidv7(),

            -- Domain columns
            listing_url TEXT NOT NULL,
            external_listing_id VARCHAR(255),
            job_board_source {SCHEMA_NAME}.job_board_source_enum NOT NULL,
            query_id UUID NOT NULL,
            correlation_id UUID,
            content_hash VARCHAR(64) NOT NULL,
            discovered_data JSONB NOT NULL,
            discovered_at TIMESTAMPTZ NOT NULL,

            -- SagaBaseMixin columns
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED', 'EXPIRED')),
            expected_callbacks INTEGER NOT NULL
                CHECK (expected_callbacks >= 1),
            received_callbacks INTEGER NOT NULL DEFAULT 0
                CHECK (received_callbacks >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
                CHECK (version >= 1),

            -- Saga invariants: callbacks cannot exceed the expected count, and
            -- listing_url must be a non-empty string (defence-in-depth against
            -- producers emitting blank URLs).
            CONSTRAINT chk_received_le_expected CHECK (received_callbacks <= expected_callbacks),
            CONSTRAINT chk_listing_url_nonempty CHECK (length(listing_url) > 0)
        )
    """)

    # Partial unique index permits a new saga for a URL once the prior saga has
    # left PENDING; only one in-flight ingest per URL at a time.
    op.execute(f"""
        CREATE UNIQUE INDEX ix_listing_ingest_saga_url_pending
        ON {SCHEMA_NAME}.listing_ingest_saga (listing_url)
        WHERE status = 'PENDING'
    """)

    op.execute(f"""
        CREATE INDEX ix_listing_ingest_saga_status_pending
        ON {SCHEMA_NAME}.listing_ingest_saga (status)
        WHERE status = 'PENDING'
    """)

    op.execute(f"""
        CREATE INDEX ix_listing_ingest_saga_expires
        ON {SCHEMA_NAME}.listing_ingest_saga (expires_at)
        WHERE status = 'PENDING'
    """)

    op.execute(f"""
        CREATE INDEX ix_listing_ingest_saga_content_hash
        ON {SCHEMA_NAME}.listing_ingest_saga (content_hash)
    """)

    op.execute(f"""
        COMMENT ON TABLE {SCHEMA_NAME}.listing_ingest_saga IS
        'In-flight saga tracking discovered listings awaiting enrichment. '
        'Promoted to listings on EnrichmentCompleted; partial unique index prevents '
        'duplicate concurrent ingests of the same URL.'
    """)

    # Create outbox table for Debezium CDC events
    op.execute(get_create_outbox_table_sql(SCHEMA_NAME))
    op.execute(get_create_outbox_indexes_sql(SCHEMA_NAME))

    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop job storage schema."""
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")

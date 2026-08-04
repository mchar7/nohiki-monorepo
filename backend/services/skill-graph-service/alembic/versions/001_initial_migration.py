"""Initial migration for skill-graph-service.

Revision ID: 001
Revises:
Create Date: 2026-01-06
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

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_NAME = "skill_graph_schema"


def _create_outbox_tables(schema: str) -> None:
    """Create event outbox and processed-events tables."""
    op.execute(get_create_outbox_table_sql(schema))
    op.execute(get_create_outbox_indexes_sql(schema))
    op.execute(get_create_processed_events_sql(schema))
    op.execute(get_create_processed_events_index_sql(schema))


def upgrade() -> None:
    """Create skill graph schema and all tables."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")

    # ════════════════════════════════════════════════════════════════════════════
    # skill_node table (canonical skills)
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(rf"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.skill_node (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            normalized_text VARCHAR(100) NOT NULL,
            display_name VARCHAR(200),
            skill_type VARCHAR(20) NOT NULL DEFAULT 'specialized',
            reuse_level VARCHAR(25),
            category VARCHAR(150),
            subcategory VARCHAR(150),
            description TEXT,
            confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            review_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            mention_count INTEGER NOT NULL DEFAULT 0,
            job_count INTEGER NOT NULL DEFAULT 0,
            profile_count INTEGER NOT NULL DEFAULT 0,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            updated_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            UNIQUE (normalized_text),
            CONSTRAINT skill_node_confidence_range CHECK (confidence_score BETWEEN 0.0 AND 1.0),
            CONSTRAINT skill_node_counts_nonnegative CHECK (
                mention_count >= 0 AND job_count >= 0 AND profile_count >= 0
            ),
            CONSTRAINT skill_node_normalized_text_format CHECK (
                LENGTH(normalized_text) BETWEEN 1 AND 100
                AND normalized_text = LOWER(normalized_text)
                AND normalized_text = BTRIM(normalized_text)
                AND normalized_text !~ '\s{{2,}}'
                AND normalized_text !~ '["'']'
            )
        )
    """)

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_node_normalized_text
        ON {SCHEMA_NAME}.skill_node (normalized_text)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_node_confidence
        ON {SCHEMA_NAME}.skill_node (confidence_score DESC)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_node_job_count
        ON {SCHEMA_NAME}.skill_node (job_count DESC)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_node_review_status
        ON {SCHEMA_NAME}.skill_node (review_status) WHERE review_status != 'approved'
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_node_created_at_brin
        ON {SCHEMA_NAME}.skill_node USING BRIN (created_at) WITH (pages_per_range = 32)
    """)

    # ════════════════════════════════════════════════════════════════════════════
    # skill_alias table (learned and seeded aliases)
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.skill_alias (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            alias_text VARCHAR(200) NOT NULL,
            canonical_skill_id UUID NOT NULL
                REFERENCES {SCHEMA_NAME}.skill_node(id) ON DELETE CASCADE,

            -- Context awareness
            context_hint VARCHAR(100),

            -- Quality tracking
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0.9,
            usage_count INTEGER NOT NULL DEFAULT 1,

            -- Provenance
            source VARCHAR(50) NOT NULL,
            source_version VARCHAR(50) NOT NULL,
            source_job_id UUID,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            updated_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},

            -- Same alias can map differently by context
            UNIQUE NULLS NOT DISTINCT (alias_text, context_hint),
            CONSTRAINT skill_alias_confidence_range CHECK (confidence BETWEEN 0.0 AND 1.0),
            CONSTRAINT skill_alias_usage_nonnegative CHECK (usage_count >= 0)
        )
    """)

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_alias_lookup
        ON {SCHEMA_NAME}.skill_alias (LOWER(alias_text), context_hint)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_alias_canonical
        ON {SCHEMA_NAME}.skill_alias (canonical_skill_id)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_alias_source
        ON {SCHEMA_NAME}.skill_alias (source)
    """)

    # ════════════════════════════════════════════════════════════════════════════
    # skill_relationship table
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.skill_relationship (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            source_skill_id UUID NOT NULL
                REFERENCES {SCHEMA_NAME}.skill_node(id) ON DELETE CASCADE,
            target_skill_id UUID NOT NULL
                REFERENCES {SCHEMA_NAME}.skill_node(id) ON DELETE CASCADE,

            -- Relationship type
            relationship_type VARCHAR(50) NOT NULL,

            -- Strength of relationship (0.0 - 1.0)
            strength DOUBLE PRECISION NOT NULL DEFAULT 1.0,

            -- Whether relationship applies in both directions
            bidirectional BOOLEAN NOT NULL DEFAULT false,

            -- Provenance
            source VARCHAR(50) NOT NULL,
            source_version VARCHAR(50) NOT NULL,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},

            UNIQUE(source_skill_id, target_skill_id, relationship_type),
            CONSTRAINT skill_rel_no_self_ref CHECK (source_skill_id != target_skill_id),
            CONSTRAINT skill_rel_strength_range CHECK (strength BETWEEN 0.0 AND 1.0)
        )
    """)

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_rel_source
        ON {SCHEMA_NAME}.skill_relationship (source_skill_id)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_rel_target
        ON {SCHEMA_NAME}.skill_relationship (target_skill_id)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_rel_type
        ON {SCHEMA_NAME}.skill_relationship (relationship_type)
    """)

    # ════════════════════════════════════════════════════════════════════════════
    # proposed_skill table (staging for review)
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.proposed_skill (
            id UUID PRIMARY KEY DEFAULT uuidv7(),

            -- Proposed skill details
            canonical_name VARCHAR(100) NOT NULL UNIQUE,
            display_name VARCHAR(200) NOT NULL,
            suggested_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
            category VARCHAR(100),
            description TEXT,
            reuse_level VARCHAR(25),

            -- NOTE: Embedding stored in Qdrant skills collection, not here

            -- Provenance tracking
            source_job_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            proposal_count INTEGER NOT NULL DEFAULT 1,
            proposed_by VARCHAR(50) NOT NULL,

            -- Review workflow
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            reviewed_at TIMESTAMPTZ,
            reviewed_by VARCHAR(100),
            rejection_reason TEXT,

            -- If approved, link to created skill
            approved_skill_id UUID
                REFERENCES {SCHEMA_NAME}.skill_node(id) ON DELETE SET NULL,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            updated_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            CONSTRAINT proposed_skill_status_values
                CHECK (status IN ('pending', 'approved', 'rejected')),
            CONSTRAINT proposed_skill_count_positive CHECK (proposal_count >= 1)
        )
    """)

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_proposed_skill_status
        ON {SCHEMA_NAME}.proposed_skill (status)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_proposed_skill_name
        ON {SCHEMA_NAME}.proposed_skill (canonical_name)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_proposed_skill_count
        ON {SCHEMA_NAME}.proposed_skill (proposal_count DESC)
    """)

    # ════════════════════════════════════════════════════════════════════════════
    # skill_seed_provenance table (per-source skill provenance)
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.skill_seed_provenance (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            skill_id UUID NOT NULL
                REFERENCES {SCHEMA_NAME}.skill_node(id) ON DELETE CASCADE,
            source_name VARCHAR(50) NOT NULL,
            source_version VARCHAR(50) NOT NULL,
            authority SMALLINT NOT NULL CHECK (authority IN (1, 2, 3)),
            external_id VARCHAR(500),
            external_uri VARCHAR(1000),
            seeded_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            updated_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            UNIQUE (skill_id, source_name)
        )
    """)

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_seed_prov_skill
        ON {SCHEMA_NAME}.skill_seed_provenance (skill_id)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_seed_prov_source
        ON {SCHEMA_NAME}.skill_seed_provenance (source_name, source_version)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_skill_seed_prov_authority
        ON {SCHEMA_NAME}.skill_seed_provenance (authority)
    """)

    # ════════════════════════════════════════════════════════════════════════════
    # seed_batch_record table (per-source, per-version seeding lifecycle)
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.seed_batch_record (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            source_name VARCHAR(50) NOT NULL,
            source_version VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed')),
            skills_added INTEGER NOT NULL DEFAULT 0,
            skills_updated INTEGER NOT NULL DEFAULT 0,
            aliases_added INTEGER NOT NULL DEFAULT 0,
            relationships_added INTEGER NOT NULL DEFAULT 0,
            occupation_relations_added INTEGER NOT NULL DEFAULT 0,
            occupations_added INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            completed_at TIMESTAMPTZ,
            error_details TEXT,
            UNIQUE (source_name, source_version),
            CONSTRAINT seed_batch_counts_nonnegative CHECK (
                skills_added >= 0
                AND skills_updated >= 0
                AND aliases_added >= 0
                AND relationships_added >= 0
                AND occupation_relations_added >= 0
                AND occupations_added >= 0
                AND error_count >= 0
            )
        )
    """)

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_seed_batch_source
        ON {SCHEMA_NAME}.seed_batch_record (source_name, source_version)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_seed_batch_status
        ON {SCHEMA_NAME}.seed_batch_record (status) WHERE status != 'completed'
    """)

    # ════════════════════════════════════════════════════════════════════════════
    # occupation_skill_relation table (source-agnostic occupation-to-skill)
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.occupation_skill_relation (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            occupation_code VARCHAR(50) NOT NULL,
            occupation_label VARCHAR(300) NOT NULL,
            skill_id UUID NOT NULL
                REFERENCES {SCHEMA_NAME}.skill_node(id) ON DELETE CASCADE,
            relation_type VARCHAR(20) NOT NULL
                CHECK (relation_type IN ('essential', 'optional', 'mentioned')),
            source_name VARCHAR(50) NOT NULL,
            source_version VARCHAR(50) NOT NULL,
            source_metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},

            UNIQUE (occupation_code, skill_id, source_name)
        )
    """)

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occupation_skill_occupation
        ON {SCHEMA_NAME}.occupation_skill_relation (occupation_code)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occupation_skill_skill
        ON {SCHEMA_NAME}.occupation_skill_relation (skill_id)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occupation_skill_relation_type
        ON {SCHEMA_NAME}.occupation_skill_relation (relation_type)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occupation_skill_source
        ON {SCHEMA_NAME}.occupation_skill_relation (source_name, source_version)
    """)

    # ════════════════════════════════════════════════════════════════════════════
    # occupation_skill_observation table (empirical occupation-skill signals)
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.occupation_skill_observation (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            occupation_code VARCHAR(50) NOT NULL,
            skill_id UUID NOT NULL
                REFERENCES {SCHEMA_NAME}.skill_node(id) ON DELETE CASCADE,
            dominant_relation VARCHAR(20) NOT NULL
                CHECK (dominant_relation IN ('essential', 'optional', 'mentioned')),
            observation_count INTEGER NOT NULL DEFAULT 1
                CHECK (observation_count >= 1),
            first_observed_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            last_observed_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},

            UNIQUE (occupation_code, skill_id)
        )
    """)

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occ_skill_obs_occupation
        ON {SCHEMA_NAME}.occupation_skill_observation (occupation_code)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occ_skill_obs_skill
        ON {SCHEMA_NAME}.occupation_skill_observation (skill_id)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occ_skill_obs_count
        ON {SCHEMA_NAME}.occupation_skill_observation (observation_count DESC)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occ_skill_obs_last_seen
        ON {SCHEMA_NAME}.occupation_skill_observation (last_observed_at DESC)
    """)

    # ════════════════════════════════════════════════════════════════════════════
    # occupation_node table (ESCO occupations for job title → occupation inference)
    # ════════════════════════════════════════════════════════════════════════════
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.occupation_node (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            occupation_code VARCHAR(50) NOT NULL UNIQUE,
            preferred_label VARCHAR(300) NOT NULL,
            description TEXT,
            alt_labels JSONB NOT NULL DEFAULT '[]'::jsonb,
            isco_group_code VARCHAR(20),
            occupation_type VARCHAR(50) NOT NULL DEFAULT 'escooccupation',
            source_name VARCHAR(50) NOT NULL,
            source_version VARCHAR(50) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()},
            updated_at TIMESTAMPTZ NOT NULL DEFAULT {sa.func.now()}
        )
    """)

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occupation_node_code
        ON {SCHEMA_NAME}.occupation_node (occupation_code)
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occupation_node_label
        ON {SCHEMA_NAME}.occupation_node USING GIN (to_tsvector('english', preferred_label))
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occupation_node_isco
        ON {SCHEMA_NAME}.occupation_node (isco_group_code) WHERE isco_group_code IS NOT NULL
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS ix_occupation_node_source
        ON {SCHEMA_NAME}.occupation_node (source_name, source_version)
    """)

    _create_outbox_tables(SCHEMA_NAME)


def downgrade() -> None:
    """Drop skill graph schema."""
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")

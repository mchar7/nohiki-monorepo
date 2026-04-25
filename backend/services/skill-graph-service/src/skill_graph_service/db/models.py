"""SQLAlchemy models for skill-graph-service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar, Final

import sqlalchemy as sa
from nohiki_db_utils import SQL_NOW, BaseEntity
from nohiki_db_utils.db_mixins import RepresentableMixin
from nohiki_db_utils.state_machine import StateMachineMixin
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SCHEMA_NAME: Final[str] = "skill_graph_schema"
CASCADE_DELETE_ORPHAN: Final[str] = "all, delete-orphan"
UUIDV7_DEFAULT = sa.text("uuidv7()")

SKILL_DEFAULT_CONFIDENCE: Final[float] = 0.5
SKILL_DEFAULT_REVIEW_STATUS: Final[str] = "pending"

SKILL_REVIEW_STATUS_PENDING: Final[str] = "pending"
SKILL_REVIEW_STATUS_APPROVED: Final[str] = "approved"

_NORMALIZED_TEXT_FORMAT_CHECK: Final[str] = (
    "LENGTH(normalized_text) BETWEEN 1 AND 100"
    " AND normalized_text = LOWER(normalized_text)"
    " AND normalized_text = BTRIM(normalized_text)"
    r" AND normalized_text !~ '\s{2,}'"
    " AND normalized_text !~ '[''\"']'"
)


class Base(DeclarativeBase):
    """Base class for all models."""


class SkillNode(BaseEntity, Base):
    """Canonical skill in the skill graph."""

    __repr_fields__ = ("id", "normalized_text", "review_status")

    __tablename__ = "skill_node"
    __table_args__ = (
        UniqueConstraint("normalized_text", name="uq_skill_node_normalized_text"),
        CheckConstraint(
            _NORMALIZED_TEXT_FORMAT_CHECK,
            name="skill_node_normalized_text_format",
        ),
        CheckConstraint(
            "confidence_score BETWEEN 0.0 AND 1.0",
            name="skill_node_confidence_range",
        ),
        CheckConstraint(
            "mention_count >= 0 AND job_count >= 0 AND profile_count >= 0",
            name="skill_node_counts_nonnegative",
        ),
        {"schema": SCHEMA_NAME},
    )

    normalized_text: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Metadata
    skill_type: Mapped[str] = mapped_column(String(20), nullable=False, default="specialized")
    reuse_level: Mapped[str | None] = mapped_column(String(25), nullable=True)
    category: Mapped[str | None] = mapped_column(String(150), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(150), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Quality tracking
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    job_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    profile_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)

    # Relationships
    aliases: Mapped[list[SkillAlias]] = relationship(
        "SkillAlias", back_populates="canonical_skill", cascade=CASCADE_DELETE_ORPHAN
    )
    outgoing_relationships: Mapped[list[SkillRelationship]] = relationship(
        "SkillRelationship",
        foreign_keys="SkillRelationship.source_skill_id",
        back_populates="source_skill",
        cascade=CASCADE_DELETE_ORPHAN,
    )
    incoming_relationships: Mapped[list[SkillRelationship]] = relationship(
        "SkillRelationship",
        foreign_keys="SkillRelationship.target_skill_id",
        back_populates="target_skill",
        cascade=CASCADE_DELETE_ORPHAN,
    )
    provenance_entries: Mapped[list[SkillSeedProvenance]] = relationship(
        "SkillSeedProvenance", back_populates="skill", cascade=CASCADE_DELETE_ORPHAN
    )


class SkillAlias(RepresentableMixin, Base):
    """Maps alternative skill names to canonical skills."""

    __tablename__ = "skill_alias"
    __table_args__ = (
        UniqueConstraint(
            "alias_text",
            "context_hint",
            name="uq_skill_alias_text_context",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="skill_alias_confidence_range"),
        CheckConstraint("usage_count >= 0", name="skill_alias_usage_nonnegative"),
        sa.Index("ix_skill_alias_lookup", sa.text("lower(alias_text)"), "context_hint"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True, server_default=UUIDV7_DEFAULT)
    alias_text: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey(f"{SCHEMA_NAME}.skill_node.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Context awareness
    context_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Quality tracking
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.9)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Provenance
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_version: Mapped[str] = mapped_column(String(50), nullable=False)
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)

    # Relationships
    canonical_skill: Mapped[SkillNode] = relationship("SkillNode", back_populates="aliases")

    __repr_fields__ = ("id", "alias_text", "canonical_skill_id")


class SkillRelationship(RepresentableMixin, Base):
    """Relationship between two skills."""

    __tablename__ = "skill_relationship"
    __table_args__ = (
        UniqueConstraint(
            "source_skill_id",
            "target_skill_id",
            "relationship_type",
            name="uq_skill_relationship_source_target_type",
        ),
        CheckConstraint("source_skill_id != target_skill_id", name="skill_rel_no_self_ref"),
        CheckConstraint("strength BETWEEN 0.0 AND 1.0", name="skill_rel_strength_range"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True, server_default=UUIDV7_DEFAULT)
    source_skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey(f"{SCHEMA_NAME}.skill_node.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey(f"{SCHEMA_NAME}.skill_node.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    bidirectional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_version: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)

    # Relationships
    source_skill: Mapped[SkillNode] = relationship(
        "SkillNode", foreign_keys=[source_skill_id], back_populates="outgoing_relationships"
    )
    target_skill: Mapped[SkillNode] = relationship(
        "SkillNode", foreign_keys=[target_skill_id], back_populates="incoming_relationships"
    )

    __repr_fields__ = ("id", "source_skill_id", "target_skill_id", "relationship_type")


class ProposedSkill(RepresentableMixin, StateMachineMixin, Base):
    """Staging table for skills proposed by LLM extraction."""

    __status_field__ = "status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "pending": frozenset({"approved", "rejected"}),
        "approved": frozenset(),
        "rejected": frozenset({"pending"}),
    }

    __tablename__ = "proposed_skill"
    __table_args__ = (
        UniqueConstraint("canonical_name", name="uq_proposed_skill_canonical_name"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="proposed_skill_status_values",
        ),
        CheckConstraint("proposal_count >= 1", name="proposed_skill_count_positive"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True, server_default=UUIDV7_DEFAULT)

    # Proposed skill details
    canonical_name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    suggested_aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reuse_level: Mapped[str | None] = mapped_column(String(25), nullable=True)

    # Provenance tracking
    source_job_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    proposal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    proposed_by: Mapped[str] = mapped_column(String(50), nullable=False)

    # Review workflow
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Link to approved skill
    approved_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(),
        ForeignKey(f"{SCHEMA_NAME}.skill_node.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)

    __repr_fields__ = ("id", "canonical_name", "status")


class OccupationSkillRelation(RepresentableMixin, Base):
    """Source-agnostic occupation-to-skill relationship for occupation-based skill filtering."""

    __tablename__ = "occupation_skill_relation"
    __table_args__ = (
        UniqueConstraint("occupation_code", "skill_id", "source_name", name="uq_occupation_skill_source"),
        CheckConstraint(
            "relation_type IN ('essential', 'optional', 'mentioned')",
            name="occupation_skill_relation_type_values",
        ),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True, server_default=UUIDV7_DEFAULT)
    occupation_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    occupation_label: Mapped[str] = mapped_column(String(300), nullable=False)
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey(f"{SCHEMA_NAME}.skill_node.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_version: Mapped[str] = mapped_column(String(50), nullable=False)
    source_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)

    __repr_fields__ = ("id", "occupation_code", "skill_id", "relation_type")


class SkillSeedProvenance(RepresentableMixin, Base):
    """Source provenance record linking a seeded skill to its origin."""

    __tablename__ = "skill_seed_provenance"
    __table_args__ = (
        UniqueConstraint("skill_id", "source_name", name="uq_skill_seed_prov_skill_source"),
        CheckConstraint("authority IN (1, 2, 3)", name="skill_seed_prov_authority_range"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True, server_default=UUIDV7_DEFAULT)
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey(f"{SCHEMA_NAME}.skill_node.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_version: Mapped[str] = mapped_column(String(50), nullable=False)
    authority: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    seeded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)

    skill: Mapped[SkillNode] = relationship("SkillNode", back_populates="provenance_entries")

    __repr_fields__ = ("id", "skill_id", "source_name", "source_version")


class SeedBatchRecord(RepresentableMixin, Base):
    """Tracks per-source, per-version seeding lifecycle and cumulative statistics."""

    __tablename__ = "seed_batch_record"
    __table_args__ = (
        UniqueConstraint("source_name", "source_version", name="uq_seed_batch_source_version"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="seed_batch_status_values",
        ),
        CheckConstraint(
            "skills_added >= 0 AND skills_updated >= 0 AND aliases_added >= 0"
            " AND relationships_added >= 0 AND occupation_relations_added >= 0"
            " AND occupations_added >= 0 AND error_count >= 0",
            name="seed_batch_counts_nonnegative",
        ),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True, server_default=UUIDV7_DEFAULT)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    skills_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skills_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aliases_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relationships_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    occupation_relations_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    occupations_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)

    __repr_fields__ = ("id", "source_name", "source_version", "status")


class OccupationNode(RepresentableMixin, Base):
    """ESCO occupation entity for job title → occupation inference embeddings."""

    __tablename__ = "occupation_node"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True, server_default=UUIDV7_DEFAULT)
    occupation_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    preferred_label: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_labels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    isco_group_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    occupation_type: Mapped[str] = mapped_column(String(50), nullable=False, default="escooccupation")
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=SQL_NOW)

    __repr_fields__ = ("id", "occupation_code", "preferred_label")

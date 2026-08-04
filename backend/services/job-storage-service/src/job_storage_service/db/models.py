"""Database models for job-storage-service (job-storage domain).

Schema: job_storage_schema
Tables: listings (post-enrichment canonical), listing_versions (history),
        listing_ingest_saga (pre-enrichment in-flight tracking).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from nohiki.common.v1 import (
    EmploymentTerm,
    JobBoardSource,
    ListingStatus,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki_db_utils import BaseEntity, SagaBaseMixin, StateMachineMixin
from nohiki_db_utils.db_mixins import RepresentableMixin
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_NAME = "job_storage_schema"


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


# Define enums for job storage schema
WorkArrangementEnum = SQLEnum(
    WorkArrangement,
    name="work_arrangement_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

EmploymentTermEnum = SQLEnum(
    EmploymentTerm,
    name="employment_term_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

SeniorityLevelEnum = SQLEnum(
    SeniorityLevel,
    name="seniority_level_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

JobBoardSourceEnum = SQLEnum(
    JobBoardSource,
    name="job_board_source_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

ListingStatusEnum = SQLEnum(
    ListingStatus,
    name="listing_status_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)


class Listing(BaseEntity, StateMachineMixin, Base):
    """Canonical job listing - user-agnostic, from scraped sources."""

    __repr_fields__ = ("id", "title", "company_name", "status")
    __status_field__ = "status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "ACTIVE": frozenset({"STALE", "EXPIRED"}),
        "STALE": frozenset({"ACTIVE", "EXPIRED"}),
        "EXPIRED": frozenset(),
    }

    __tablename__ = "listings"
    __table_args__ = (
        sa.Index("ix_listings_url", "listing_url", unique=True),
        sa.Index("ix_listings_search_vector", "search_vector", postgresql_using="gin"),
        sa.Index(
            "ix_listings_discovered_at_brin",
            "discovered_at",
            postgresql_using="brin",
            postgresql_with={"pages_per_range": 32},
        ),
        sa.Index(
            "ix_listings_created_at_brin",
            "created_at",
            postgresql_using="brin",
            postgresql_with={"pages_per_range": 32},
        ),
        sa.Index("ix_listings_source_hash", "job_board_source", postgresql_using="hash"),
        sa.Index(
            "ix_listings_location_gin",
            "location",
            postgresql_using="gin",
            postgresql_ops={"location": "jsonb_path_ops"},
        ),
        sa.Index("ix_listings_skills_gin", "required_skills", postgresql_using="gin"),
        sa.Index("ix_listings_work_arrangement", "work_arrangement"),
        sa.Index(
            "ix_listings_active",
            sa.text("created_at DESC"),
            postgresql_where=sa.text("status = 'ACTIVE'"),
        ),
        sa.Index("ix_listings_dedup", "dedup_hash", unique=True),
        sa.Index("ix_listings_content_hash", "raw_content_hash"),
        {"schema": SCHEMA_NAME},
    )

    # Identification
    listing_url: Mapped[str] = mapped_column(Text, nullable=False)
    job_board_source: Mapped[JobBoardSource] = mapped_column(JobBoardSourceEnum, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Core details
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    company_logo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Location (structured form populated during enrichment; raw scrape strings
    # never reach this table).
    location: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Classification
    work_arrangement: Mapped[WorkArrangement] = mapped_column(
        WorkArrangementEnum,
        nullable=False,
        server_default=WorkArrangement.UNSPECIFIED.name,
    )
    employment_term: Mapped[EmploymentTerm] = mapped_column(
        EmploymentTermEnum,
        nullable=False,
        server_default=EmploymentTerm.UNSPECIFIED.name,
    )
    seniority_level: Mapped[SeniorityLevel] = mapped_column(
        SeniorityLevelEnum,
        nullable=False,
        server_default=SeniorityLevel.UNSPECIFIED.name,
    )
    language: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        server_default=sa.text("'und'"),
        comment="IETF BCP 47 language tag of the listing text (e.g. 'en', 'fr-CA', 'zh-CN')",
    )

    # Requirements
    required_skills: Mapped[list[str]] = mapped_column(
        PG_ARRAY(Text),
        nullable=False,
        server_default=sa.text("ARRAY[]::text[]"),
    )
    min_experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Canonical skill IDs from skill-graph-service
    canonical_skill_ids: Mapped[list[str] | None] = mapped_column(
        PG_ARRAY(Text),
        nullable=True,
        comment="UUIDs of canonical skills from skill-graph-service",
    )

    # Pre-computed embeddings for semantic matching
    skills_embedding: Mapped[list[float] | None] = mapped_column(
        PG_ARRAY(sa.Float),
        nullable=True,
        comment="Aggregated skill embedding (dimension from manifest)",
    )
    title_embedding: Mapped[list[float] | None] = mapped_column(
        PG_ARRAY(sa.Float),
        nullable=True,
        comment="Title embedding (dimension from manifest)",
    )

    # Collection version for embedding compatibility tracking
    collection_version: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Qdrant collection version (e.g., 'v1') from manifest",
    )

    # Compensation (raw from scrape)
    compensation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Status & versioning
    status: Mapped[ListingStatus] = mapped_column(
        ListingStatusEnum,
        nullable=False,
        server_default=ListingStatus.ACTIVE.name,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("1"))

    # Content change detection (SHA-256 hash of raw listing data)
    raw_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Cross-source deduplication hash
    # SHA-256 of normalized: lowercase(title) + lowercase(company_name) + date(posted_at)
    dedup_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Full-text search vector maintained by the database trigger.
    search_vector: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)

    # Timestamps
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # BaseEntity provides: id, created_at, updated_at


class ListingVersion(RepresentableMixin, Base):
    """Version history for job listings, storing full snapshots for audit and change tracking."""

    __tablename__ = "listing_versions"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    # Primary key
    id: Mapped[Any] = mapped_column(
        sa.UUID,
        primary_key=True,
        server_default=sa.text("uuidv7()"),
    )

    # Reference to the parent listing
    listing_id: Mapped[Any] = mapped_column(
        sa.UUID,
        sa.ForeignKey(f"{SCHEMA_NAME}.listings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Version number at the time of this snapshot
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Content hash at the time of this version
    raw_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Full snapshot of the listing state at this version (JSONB)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Change metadata
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'created', 'updated', 'enriched'
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Processing context
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    __repr_fields__ = ("id", "listing_id", "version", "change_type")


class ListingIngestSaga(SagaBaseMixin, Base):
    """In-flight tracking for discovered listings awaiting enrichment.

    A saga row represents the lifecycle from ListingDiscovered (PENDING) to
    EnrichmentCompleted (COMPLETED). The canonical ``listings`` table receives
    a row only on completion, after enrichment has supplied structured location
    and a description that satisfies the listings constraints.

    The saga ID is the stable identifier carried as ``ListingReference.listing_id``
    through the ``ListingAccepted`` -> enrichment -> ``EnrichmentCompleted`` chain,
    and becomes the ``listings.id`` on completion. This anchors the same UUID
    across the entire lifecycle for cross-service tracing.
    """

    __tablename__ = "listing_ingest_saga"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    listing_url: Mapped[str] = mapped_column(Text, nullable=False)
    external_listing_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_board_source: Mapped[JobBoardSource] = mapped_column(JobBoardSourceEnum, nullable=False)
    query_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    discovered_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

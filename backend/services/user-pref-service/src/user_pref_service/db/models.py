"""SQLAlchemy models for user-pref-service (user-pref domain).

Schema: user_pref_schema
Tables: search_prefs, search_pref_uploads

Field names align with SearchPrefSnapshot proto from nohiki.user.pref.v1.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from nohiki.common.v1 import JobBoardSource, SeniorityLevel, WorkArrangement
from nohiki_db_utils import BaseEntity, SagaBaseMixin
from nohiki_db_utils.db_mixins import RepresentableMixin
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import ARRAY, DOUBLE_PRECISION, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SCHEMA_NAME = "user_pref_schema"
SQL_EMPTY_JSONB_ARRAY = sa.text("'[]'::jsonb")
SQL_EMPTY_VARCHAR_ARRAY = sa.text("ARRAY[]::varchar[]")

WorkArrangementEnum = SQLEnum(
    WorkArrangement,
    name="work_arrangement_enum",
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

SeniorityLevelEnum = SQLEnum(
    SeniorityLevel,
    name="seniority_level_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)


class Base(DeclarativeBase):
    """Base class for all models."""


class SearchPref(BaseEntity, Base):
    """Account's job search preferences.

    Field names match SearchPrefSnapshot proto for direct mapping.
    """

    __repr_fields__ = ("id", "pref_name", "user_id")

    __tablename__ = "search_prefs"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)

    pref_name: Mapped[str] = mapped_column(String(100), nullable=False)
    search_keywords: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    disallowed_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, server_default=SQL_EMPTY_VARCHAR_ARRAY
    )

    physical_locations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=SQL_EMPTY_JSONB_ARRAY
    )
    remote_locations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=SQL_EMPTY_JSONB_ARRAY
    )

    open_to_relocation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))
    commute_preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    work_arrangements: Mapped[list[WorkArrangement]] = mapped_column(
        ARRAY(WorkArrangementEnum),
        nullable=False,
    )

    experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seniority_levels: Mapped[list[SeniorityLevel]] = mapped_column(
        ARRAY(SeniorityLevelEnum),
        nullable=False,
        server_default=sa.text(f"ARRAY[]::{SCHEMA_NAME}.seniority_level_enum[]"),
    )
    salary_preference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    feature_importance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    excluded_scrape_sources: Mapped[list[JobBoardSource]] = mapped_column(
        ARRAY(JobBoardSourceEnum),
        nullable=False,
        server_default=sa.text(f"ARRAY[]::{SCHEMA_NAME}.job_board_source_enum[]"),
    )

    min_fit_score_disqualify: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_tailor_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tailoring_schema_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    tailoring_preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    notification_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("true"), nullable=False)

    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True, unique=True, index=True)

    user_skill_ids: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(100)), nullable=True, server_default=SQL_EMPTY_VARCHAR_ARRAY
    )
    user_skills_data: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    user_skills_embedding: Mapped[list[float] | None] = mapped_column(ARRAY(DOUBLE_PRECISION), nullable=True)
    query_embedding: Mapped[list[float] | None] = mapped_column(ARRAY(DOUBLE_PRECISION), nullable=True)
    query_artifacts_data: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    semantic_content_generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("0"))
    semantic_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collection_version: Mapped[str | None] = mapped_column(String(10), nullable=True)

    enrichment_terminal_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    attachments: Mapped[list[SearchPrefUpload]] = relationship(
        "SearchPrefUpload", back_populates="search_pref", cascade="all, delete-orphan"
    )


class PrefEnrichmentAction(StrEnum):
    """Lifecycle fact emitted when preference enrichment completes."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"


class PrefEnrichmentSaga(SagaBaseMixin, Base):
    """Durable callback and retry state for preference enrichment."""

    __tablename__ = "pref_enrichment_saga"
    __table_args__ = (
        sa.Index("ix_pref_enrichment_saga_pref_id", "pref_id"),
        sa.Index(
            "uq_pref_enrichment_saga_pending_pref",
            "pref_id",
            unique=True,
            postgresql_where=sa.text("status = 'PENDING'"),
        ),
        sa.Index(
            "ix_pref_enrichment_saga_status_pending",
            "status",
            postgresql_where=sa.text("status = 'PENDING'"),
        ),
        sa.Index(
            "ix_pref_enrichment_saga_expires",
            "expires_at",
            postgresql_where=sa.text("status = 'PENDING'"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','COMPLETED','FAILED','EXPIRED','CANCELLED')",
            name="pref_enrichment_saga_status_check",
        ),
        sa.CheckConstraint(
            "action IN ('CREATE','UPDATE')",
            name="pref_enrichment_saga_action_check",
        ),
        sa.CheckConstraint("attempts_remaining >= 0", name="pref_enrichment_saga_attempts_nonnegative"),
        {"schema": SCHEMA_NAME},
    )

    pref_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey(f"{SCHEMA_NAME}.search_prefs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, unique=True)
    action: Mapped[PrefEnrichmentAction] = mapped_column(
        SQLEnum(
            PrefEnrichmentAction,
            native_enum=False,
            create_type=False,
            values_callable=lambda enum: [value.value for value in enum],
            length=16,
            validate_strings=True,
        ),
        nullable=False,
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_skills: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=SQL_EMPTY_JSONB_ARRAY)
    last_dispatch_ids: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    skills_persisted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))
    embedding_persisted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))
    semantic_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_step: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)


class SearchPrefUpload(RepresentableMixin, Base):
    """Association between search preferences and user uploads."""

    __tablename__ = "search_pref_uploads"
    __table_args__ = (
        sa.PrimaryKeyConstraint("pref_id", "upload_id"),
        {"schema": SCHEMA_NAME},
    )

    pref_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey(f"{SCHEMA_NAME}.search_prefs.id", ondelete="CASCADE"),
        nullable=False,
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    upload_type: Mapped[str] = mapped_column(String(50), nullable=False)

    search_pref: Mapped[SearchPref] = relationship("SearchPref", back_populates="attachments")

    __repr_fields__ = ("pref_id", "upload_id", "upload_type")


class UserPrefSettings(BaseEntity, Base):
    """User-level preference settings.

    Contains user-level defaults that apply to all search preferences
    unless overridden at the per-search-pref level.

    Owned by user-pref-service (NOT user-auth-service).
    """

    __tablename__ = "user_pref_settings"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, unique=True, index=True)

    default_feature_importance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    preferred_timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preferred_locale: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __repr_fields__ = ("id", "user_id")

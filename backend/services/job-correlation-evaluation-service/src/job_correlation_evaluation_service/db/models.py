"""Database models for job-correlation-evaluation-service (job-correlation domain).

Schema: job_correlation_schema
Tables: correlations, profile_projections, user_contact_projections
"""

import uuid
from datetime import datetime
from typing import ClassVar

import sqlalchemy as sa
from nohiki.common.v1 import CorrelationStatus, UserFeedback
from nohiki_db_utils import BaseEntity, StateMachineMixin
from nohiki_db_utils.db_mixins import RepresentableMixin
from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_NAME = "job_correlation_schema"
SQL_NOW = sa.text("now()")


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


# Define enums for job correlation schema
CorrelationStatusEnum = SQLEnum(
    CorrelationStatus,
    name="correlation_status_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name.lower() for v in e],
)

UserFeedbackEnum = SQLEnum(
    UserFeedback,
    name="user_feedback_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name.lower() for v in e],
)


class Correlation(BaseEntity, StateMachineMixin, Base):
    """Correlation between a job listing and a user's search preference.

    IMPORTANT: This table stores ALL job-user correlations, including:
    - 0% correlations (not recommendations)
    - unseen jobs
    - dismissed jobs
    - applied jobs

    This is NOT a "recommendation" table - a 0% correlation is still a correlation.

    Features:
    - UUIDv7 primary key (time-sortable)
    - is_actionable VIRTUAL generated column (computed on read, not stored)

    Note: No cross-schema FKs per EDA best practices. Listing deletion is handled via
    job-listing.cdc.listing-deleted.v1 events for eventual consistency.
    """

    __repr_fields__ = ("id", "pref_id", "listing_id", "correlation_status")
    __status_field__ = "correlation_status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "PENDING": frozenset({"EVALUATED"}),
        "EVALUATED": frozenset({"VIEWED", "DISMISSED", "EXPIRED"}),
        "VIEWED": frozenset({"SAVED", "APPLIED", "DISMISSED", "EXPIRED"}),
        "SAVED": frozenset({"APPLIED", "DISMISSED", "EXPIRED"}),
        "APPLIED": frozenset({"EXPIRED"}),
        "DISMISSED": frozenset(),
        "EXPIRED": frozenset(),
    }

    __tablename__ = "correlations"
    __table_args__ = (
        UniqueConstraint("pref_id", "listing_id", name="uq_correlation_pref_listing"),
        {"schema": SCHEMA_NAME},
    )

    # References (logical FKs - no enforcement per EDA)
    pref_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    listing_url: Mapped[str] = mapped_column(Text, nullable=False)

    # Correlation metadata
    correlation_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_reasoning: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    correlation_status: Mapped[CorrelationStatus] = mapped_column(
        CorrelationStatusEnum, nullable=False, server_default="pending"
    )

    # Account interaction tracking
    is_viewed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))
    is_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))
    is_dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))
    user_feedback: Mapped[UserFeedback | None] = mapped_column(UserFeedbackEnum, nullable=True)

    # Stored generated column - computed and stored on write
    # True when status IN ('evaluated', 'pending') AND is_dismissed = false
    is_actionable: Mapped[bool] = mapped_column(
        Boolean,
        Computed(
            "correlation_status IN ('evaluated', 'pending') AND is_dismissed = false",
            persisted=True,
        ),
        nullable=True,
    )

    # ML Training data
    feature_vector: Mapped[list[float] | None] = mapped_column(
        sa.ARRAY(sa.Float),
        nullable=True,
        comment="L2R feature vector stored at scoring time",
    )
    feature_schema_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="Model version that defined the feature layout",
    )

    # Timestamps
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # BaseEntity provides: id, created_at, updated_at


class ProfileProjection(RepresentableMixin, Base):
    """Projection of search preferences from user-pref-service events.

    Populated by: pref.created.v1, pref.updated.v1, pref.deleted.v1
    Purpose: Provides all active profiles for job matching
    """

    __tablename__ = "profile_projections"
    __table_args__ = (
        sa.Index("ix_profile_projections_user_id", "user_id"),
        sa.Index("ix_profile_projections_is_active", "is_active"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    profile_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("true"))
    source_revision: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Serialized SearchPrefSnapshot proto as JSONB for flexibility
    snapshot_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)

    __repr_fields__ = ("id", "profile_name", "is_active")

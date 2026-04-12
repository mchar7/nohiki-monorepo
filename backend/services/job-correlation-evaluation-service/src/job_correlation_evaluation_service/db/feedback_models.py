"""Database models for feedback collection in job-correlation-evaluation-service.

Schema: feedback
Tables: asymmetric_feedback, manual_adjustments

These models support the L2R personalization system by storing user feedback
on correlation scores.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from nohiki.feedback.v1 import ScoreFeedbackType
from nohiki_db_utils.db_mixins import RepresentableMixin
from sqlalchemy import CheckConstraint, Double, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base

FEEDBACK_SCHEMA = "feedback"
SQL_NOW = sa.text("NOW()")


class AsymmetricFeedbackModel(RepresentableMixin, Base):
    """Asymmetric feedback on correlation scores.

    Captures whether a score is accurate (GOOD), too high (TOO_HIGH),
    or too low (TOO_LOW). This provides directional feedback for
    L2R model improvement.

    feedback_type values (proto enum names stored as VARCHAR):
        GOOD - score accurately reflects match quality
        TOO_HIGH - score overstates match, should be lower
        TOO_LOW - score understates match, should be higher
    """

    __tablename__ = "asymmetric_feedback"
    __table_args__ = (
        CheckConstraint(
            "feedback_type IN ('GOOD', 'TOO_HIGH', 'TOO_LOW')",
            name="ck_feedback_type_valid",
        ),
        {"schema": FEEDBACK_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        primary_key=True,
        server_default=sa.text("uuidv7()"),
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        nullable=False,
        index=True,
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    feedback_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=SQL_NOW,
        nullable=False,
    )

    __repr_fields__ = ("id", "correlation_id", "feedback_type")

    def get_feedback_type_enum(self) -> ScoreFeedbackType:
        """Return the feedback_type as a ScoreFeedbackType enum."""
        return ScoreFeedbackType[self.feedback_type]


class ManualAdjustmentModel(RepresentableMixin, Base):
    """Manual score adjustment with user-provided reasoning.

    Provides richer signal than asymmetric feedback by specifying
    the exact score the user believes is correct, along with
    reasoning for the adjustment.

    Scores are stored as DOUBLE PRECISION (0.0-1.0 range).
    Validation is performed at the API/protobuf layer, not in the database.
    """

    __tablename__ = "manual_adjustments"
    __table_args__ = ({"schema": FEEDBACK_SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        primary_key=True,
        server_default=sa.text("uuidv7()"),
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        nullable=False,
        index=True,
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    original_score: Mapped[float] = mapped_column(
        Double,
        CheckConstraint(
            "original_score >= 0.0 AND original_score <= 1.0",
            name="ck_manual_adjustment_original_score_range",
        ),
        nullable=False,
    )
    adjusted_score: Mapped[float] = mapped_column(
        Double,
        CheckConstraint(
            "adjusted_score >= 0.0 AND adjusted_score <= 1.0",
            name="ck_manual_adjustment_adjusted_score_range",
        ),
        nullable=False,
    )
    reasoning: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=SQL_NOW,
        nullable=False,
    )

    __repr_fields__ = ("id", "correlation_id", "original_score", "adjusted_score")

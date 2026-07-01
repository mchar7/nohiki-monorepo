"""Durable access-token revocation ledger models."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from bff_service.db.models.base import SCHEMA_NAME, Base


class RevokedAccessToken(Base):
    """An access-token JTI revoked until its original expiry."""

    __tablename__ = "revoked_access_tokens"
    __table_args__ = (
        sa.Index("ix_revoked_access_tokens_expires_at", "expires_at"),
        {"schema": SCHEMA_NAME},
    )

    jti: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class RevokedSessionFamily(Base):
    """A refresh-token family revoked for access tokens issued before a cutoff."""

    __tablename__ = "revoked_session_families"
    __table_args__ = (
        sa.Index("ix_revoked_session_families_expires_at", "expires_at"),
        {"schema": SCHEMA_NAME},
    )

    family_id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    revoked_before: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class UserRevocationCutoff(Base):
    """User-wide token cutoff, permanent for deleted accounts."""

    __tablename__ = "user_revocation_cutoffs"
    __table_args__ = (
        sa.Index("ix_user_revocation_cutoffs_expires_at", "expires_at"),
        {"schema": SCHEMA_NAME},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    revoked_before: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    is_permanent: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=False)

"""User-domain projection models (auth, preferences, uploads)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from nohiki.common.v1 import WorkArrangement
from nohiki_db_utils import RepresentableMixin
from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from bff_service.db.models.base import SCHEMA_NAME, SQL_GEN_UUID, SQL_NOW, Base, WorkArrangementEnum


class AccountProjection(Base, RepresentableMixin):
    """Projection of user accounts from user-auth-service events (ECST)."""

    __repr_fields__ = ("id", "email", "display_name")

    __tablename__ = "account_projections"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("true"), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("false"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileProjection(Base, RepresentableMixin):
    """Projection of job target profiles from user-pref-service events."""

    __repr_fields__ = ("id", "user_id", "profile_name")

    __tablename__ = "profile_projections"
    __table_args__ = (
        sa.Index("ix_profile_projections_user_id", "user_id"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    profile_name: Mapped[str] = mapped_column(String(100), nullable=False)
    search_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}", nullable=False)
    disallowed_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}", nullable=False)
    user_skills: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}", nullable=False)
    work_arrangements: Mapped[list[WorkArrangement]] = mapped_column(
        ARRAY(WorkArrangementEnum),
        nullable=False,
        server_default=sa.text(f"ARRAY[]::{SCHEMA_NAME}.work_arrangement_enum[]"),
    )
    notification_threshold: Mapped[float] = mapped_column(Float, server_default="0.7", nullable=False)
    auto_tailor_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    tailoring_schema_id: Mapped[uuid.UUID | None] = mapped_column(UUID(), nullable=True)
    feature_importance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    open_to_relocation: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("false"), nullable=False)
    commute_preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    salary_preference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    experience_preference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserPrefSettingsProjection(Base, RepresentableMixin):
    """Projection of user preference settings from user-pref-service events."""

    __repr_fields__ = ("id", "user_id")

    __tablename__ = "user_pref_settings_projections"
    __table_args__ = (
        sa.Index("ix_user_pref_settings_projections_user_id", "user_id"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True, server_default=SQL_GEN_UUID)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, unique=True)
    default_feature_importance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    preferred_timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preferred_locale: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)


class AttachmentProjection(Base, RepresentableMixin):
    """Projection of attachments from user-upload-service events."""

    __repr_fields__ = ("id", "filename", "content_type")

    __tablename__ = "attachment_projections"
    __table_args__ = (
        sa.Index("ix_attachment_projections_user_id", "user_id"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

"""Skill-domain projection models."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from nohiki_db_utils import RepresentableMixin
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from bff_service.db.models.base import SCHEMA_NAME, SQL_NOW, Base


class SkillProjection(Base, RepresentableMixin):
    """Projection of canonical skills from skill-graph-service events."""

    __repr_fields__ = ("id", "normalized_text", "category")

    __tablename__ = "skill_projections"
    __table_args__ = (
        sa.Index("ix_skill_projections_normalized_text", "normalized_text"),
        sa.Index("ix_skill_projections_category", "category"),
        sa.Index(
            "ix_skill_projections_search",
            "search_vector",
            postgresql_using="gin",
        ),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    canonical_id: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    normalized_text: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(200), nullable=True)
    skill_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reuse_level: Mapped[str | None] = mapped_column(String(25), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="TABIYA")
    mention_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    job_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    profile_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    search_vector = sa.Column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)

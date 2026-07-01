"""Job-domain projection models (listings, correlations)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from nohiki_db_utils import RepresentableMixin
from sqlalchemy import BigInteger, DateTime, Double, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from bff_service.db.models.base import SCHEMA_NAME, SQL_NOW, Base


class JobListingProjection(Base, RepresentableMixin):
    """Projection of job listings from job-storage-service events."""

    __repr_fields__ = ("id", "title", "company_name")

    __tablename__ = "job_listing_projections"
    __table_args__ = (
        sa.Index("ix_job_listing_projections_company", "company_name"),
        sa.Index("ix_job_listing_projections_created_at", "created_at"),
        sa.Index("ix_job_listing_projections_language", "language"),
        sa.Index("ix_job_listing_projections_search", "search_vector", postgresql_using="gin"),
        sa.Index("ix_job_listing_projections_country_code", "country_code"),
        sa.Index("ix_job_listing_projections_country_posted", "country_code", "posted_at"),
        sa.Index("ix_job_listing_projections_posted_at", "posted_at"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    listing_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location_raw: Mapped[str] = mapped_column(String(500), nullable=False)
    work_arrangement: Mapped[str | None] = mapped_column(String(50), nullable=True)
    seniority_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    language: Mapped[str | None] = mapped_column(
        String(5),
        nullable=True,
        comment="IETF BCP 47 language tag of the listing text (e.g. 'en', 'fr-CA', 'zh-CN')",
    )
    required_skills: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}", nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("1"))
    raw_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    search_vector = sa.Column(TSVECTOR, nullable=True)
    salary_min: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    salary_frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    company_logo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    experience_years_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experience_years_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Double, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Double, nullable=True)


class JobCorrelationProjection(Base, RepresentableMixin):
    """Projection of job correlations from job-correlation-evaluation-service events."""

    __repr_fields__ = ("id", "pref_id", "listing_id", "fit_score", "status")

    __tablename__ = "job_correlation_projections"
    __table_args__ = (
        sa.Index("ix_job_correlation_projections_user_id", "user_id"),
        sa.Index("ix_job_correlation_projections_pref_id", "pref_id"),
        sa.Index("ix_job_correlation_projections_fit_score", "fit_score"),
        sa.UniqueConstraint("pref_id", "listing_id", name="uq_correlation_pref_listing"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    pref_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False)
    fit_score: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), server_default="pending", nullable=False)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    fit_ranking_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    pref_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    pref_uploads: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    listing_title: Mapped[str] = mapped_column(String(500), nullable=False)
    listing_company: Mapped[str | None] = mapped_column(String(500), nullable=True)
    listing_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    listing_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)

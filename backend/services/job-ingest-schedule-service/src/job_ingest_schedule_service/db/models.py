"""SQLAlchemy models for job-ingest-schedule-service (job-schedule domain).

Schema: job_schedule_schema
Tables: ingestion_schedules

NOTE: This module uses domain model enums (WorkArrangement, JobBoardSource) throughout.
SQLAlchemy handles conversion to/from PostgreSQL enum types at the boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from nohiki.common.v1 import JobBoardSource, WorkArrangement
from nohiki_db_utils import CreatedAtMixin, UpdatedAtMixin
from nohiki_db_utils.db_mixins import RepresentableMixin
from sqlalchemy import Boolean, DateTime, Integer, Interval, String
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_NAME = "job_schedule_schema"

# PostgreSQL enum types (values match proto enum names exactly)
work_arrangement_pg_enum = ENUM(
    "UNSPECIFIED",
    "ON_SITE",
    "HYBRID",
    "REMOTE",
    name="work_arrangement_enum",
    schema=SCHEMA_NAME,
    create_type=False,
)

job_board_source_pg_enum = ENUM(
    "UNSPECIFIED",
    "INDEED",
    "LINKEDIN",
    "ZIPRECRUITER",
    "GOOGLE",
    "GLASSDOOR",
    "BAYT",
    "NAUKRI",
    "COMPANY_WEBSITE",
    name="job_board_source_enum",
    schema=SCHEMA_NAME,
    create_type=False,
)

SQL_EMPTY_WORK_ARR_ARRAY = sa.text(f"ARRAY[]::{SCHEMA_NAME}.work_arrangement_enum[]")
SQL_EMPTY_SOURCE_ARRAY = sa.text(f"ARRAY[]::{SCHEMA_NAME}.job_board_source_enum[]")


class Base(DeclarativeBase):
    """Base class for all models."""


class IngestionSchedule(RepresentableMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Ingestion schedule materialized from job-query-composition-service events.

    Denormalizes ingestion query data for efficient cron processing.
    The scheduler service does NOT own this data - it's a materialized view
    of events from job-query-composition-service.
    """

    __tablename__ = "ingestion_schedules"
    __table_args__ = (
        sa.CheckConstraint("frequency > INTERVAL '0 seconds'", name="ck_schedule_frequency_positive"),
        sa.CheckConstraint("hours_old BETWEEN 1 AND 168", name="ck_schedule_hours_old_range"),
        sa.CheckConstraint("results_wanted BETWEEN 1 AND 100", name="ck_schedule_results_wanted_range"),
        {"schema": SCHEMA_NAME},
    )

    # Primary key - matches query_id from job-query-composition-service
    query_id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)

    # Denormalized query parameters (from scrape_query.*.v1 events)
    search_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    locations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # NOTE: DB stores enum strings, Python uses proto enums via property accessors
    _work_arrangements: Mapped[list[str]] = mapped_column(
        "work_arrangements", ARRAY(work_arrangement_pg_enum), nullable=False, server_default=SQL_EMPTY_WORK_ARR_ARRAY
    )
    _sources: Mapped[list[str]] = mapped_column(
        "sources", ARRAY(job_board_source_pg_enum), nullable=False, server_default=SQL_EMPTY_SOURCE_ARRAY
    )

    # Backend-controlled parameters (NOT from events)
    hours_old: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("72"))
    results_wanted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("50"))

    # Scheduling state
    frequency: Mapped[timedelta] = mapped_column(Interval, nullable=False, server_default=sa.text("'1 day'::interval"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def work_arrangements(self) -> list[WorkArrangement]:
        """Get work arrangements as proto enums."""
        return [WorkArrangement[name] for name in (self._work_arrangements or []) if name != "UNSPECIFIED"]

    @work_arrangements.setter
    def work_arrangements(self, values: list[WorkArrangement]) -> None:
        """Set work arrangements from proto enums."""
        self._work_arrangements = [v.name for v in values if v != WorkArrangement.UNSPECIFIED]

    @property
    def sources(self) -> list[JobBoardSource]:
        """Get sources as proto enums."""
        return [JobBoardSource[name] for name in (self._sources or []) if name != "UNSPECIFIED"]

    @sources.setter
    def sources(self, values: list[JobBoardSource]) -> None:
        """Set sources from proto enums."""
        self._sources = [v.name for v in values if v != JobBoardSource.UNSPECIFIED]

    __repr_fields__ = ("query_id", "is_active", "next_run_at")

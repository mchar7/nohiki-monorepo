"""SQLAlchemy models for job-query-composition-service (job-query domain).

Schema: job_query_schema
Tables: ingestion_queries, query_contributors

NOTE: This module uses domain model enums (WorkArrangement, JobBoardSource) throughout.
SQLAlchemy handles conversion to/from PostgreSQL enum types at the boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from nohiki.common.v1 import JobBoardSource, WorkArrangement
from nohiki_db_utils import CreatedAtMixin, IdMixin, UpdatedAtMixin
from nohiki_db_utils.db_mixins import RepresentableMixin
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Interval, String
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SCHEMA_NAME = "job_query_schema"

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
SQL_EMPTY_VARCHAR_ARRAY = sa.text("ARRAY[]::varchar[]")


class Base(DeclarativeBase):
    """Base class for all models."""


class IngestionQuery(RepresentableMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Deduplicated ingestion query clustered from user search preferences."""

    __tablename__ = "ingestion_queries"
    __table_args__ = (
        sa.CheckConstraint("locations IS JSON ARRAY", name="chk_locations_json_array"),
        sa.UniqueConstraint(
            "search_keywords",
            "locations",
            name="uq_ingestion_queries_canonical",
        ),
        {"schema": SCHEMA_NAME},
    )

    # Deduplication key (immutable once created)
    search_keywords: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    locations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    # Directly stored aggregates (recomputed on change)
    # NOTE: DB stores enum strings, Python uses proto enums via property accessors
    _work_arrangements: Mapped[list[str]] = mapped_column(
        "work_arrangements", ARRAY(work_arrangement_pg_enum), nullable=False, server_default=SQL_EMPTY_WORK_ARR_ARRAY
    )
    remote_preferences: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default=SQL_EMPTY_VARCHAR_ARRAY
    )
    _sources: Mapped[list[str]] = mapped_column(
        "sources", ARRAY(job_board_source_pg_enum), nullable=False, server_default=SQL_EMPTY_SOURCE_ARRAY
    )
    frequency: Mapped[timedelta] = mapped_column(Interval, nullable=False, server_default=sa.text("'1 day'::interval"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.false())

    # Contributor counts
    active_contributor_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("0"))
    total_contributor_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("0"))

    # Recomputation tracking
    last_recomputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    contributors: Mapped[list[QueryContributor]] = relationship(
        "QueryContributor", back_populates="query", cascade="all, delete-orphan"
    )

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

    __repr_fields__ = ("id", "search_keywords", "is_active")


class QueryContributor(RepresentableMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """Profile contribution to a scrape query."""

    __tablename__ = "query_contributors"
    __table_args__ = (
        sa.UniqueConstraint("pref_id", name="uq_query_contributors_pref_id"),
        {"schema": SCHEMA_NAME},
    )
    __allow_unmapped__ = True
    previous_query_id: uuid.UUID | None = None

    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(), ForeignKey(f"{SCHEMA_NAME}.ingestion_queries.id", ondelete="CASCADE"), primary_key=True
    )
    pref_id: Mapped[uuid.UUID] = mapped_column(UUID(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)

    # Individual preferences (used for aggregation)
    _work_arrangements: Mapped[list[str]] = mapped_column(
        "work_arrangements", ARRAY(work_arrangement_pg_enum), nullable=False, server_default=SQL_EMPTY_WORK_ARR_ARRAY
    )
    remote_preference: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sa.text("'any'"))
    _sources: Mapped[list[str]] = mapped_column(
        "sources", ARRAY(job_board_source_pg_enum), nullable=False, server_default=SQL_EMPTY_SOURCE_ARRAY
    )
    frequency_tier: Mapped[str] = mapped_column(String(10), nullable=False, server_default=sa.text("'daily'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.true())

    # Relationships
    query: Mapped[IngestionQuery] = relationship("IngestionQuery", back_populates="contributors")

    __repr_fields__ = ("query_id", "pref_id", "is_active")

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

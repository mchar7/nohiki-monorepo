"""Freshness tracking mixin for resource usage and staleness detection.

Provides columns and methods to track when a resource was last used,
how many times it has been used, and whether it should be considered
stale based on a configurable inactivity window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column


class FreshnessTrackingMixin:
    """Tracks resource usage frequency and detects staleness.

    Adds ``last_used_at`` and ``usage_count`` columns to any ORM model.
    The staleness window is configurable per-model via ``__staleness_days__``.

    Example::

        class DocumentTemplate(BaseEntity, FreshnessTrackingMixin, Base):
            __staleness_days__ = 90
            ...

        # Record usage after a successful render
        template.record_usage()

        # Check if template is stale
        if template.is_stale:
            logger.warning("Template hasn't been used recently")

    Attributes:
        __staleness_days__: Number of days of inactivity before a resource
            is considered stale. Defaults to 90.

    """

    __staleness_days__: ClassVar[int] = 90

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp of most recent usage",
    )
    usage_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=sa.text("0"),
        nullable=False,
        comment="Total number of times this resource has been used",
    )

    def record_usage(self) -> None:
        """Record a usage event, updating timestamp and incrementing counter."""
        self.last_used_at = datetime.now(UTC)
        self.usage_count += 1

    @property
    def is_stale(self) -> bool:
        """Check if resource hasn't been used within the staleness window.

        A resource that has **never** been used (``last_used_at is None``)
        is considered stale.
        """
        if self.last_used_at is None:
            return True
        cutoff = datetime.now(UTC) - timedelta(days=self.__staleness_days__)
        return self.last_used_at < cutoff

    @property
    def days_since_last_use(self) -> int | None:
        """Return the number of days since last usage, or None if never used."""
        if self.last_used_at is None:
            return None
        delta = datetime.now(UTC) - self.last_used_at
        return delta.days

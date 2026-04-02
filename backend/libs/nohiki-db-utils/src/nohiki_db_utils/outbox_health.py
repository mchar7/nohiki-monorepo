"""Outbox health probe (alerts if Debezium is falling behind)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nohiki_common_exceptions import (
    HealthProbeResult,
    HealthStatus,
)
from sqlalchemy import Column, Integer, MetaData, Table, func, select
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession


class OutboxHealthProbe:
    """Check outbox table backlog; high count means Debezium may be lagging.

    Debezium reads from PostgreSQL WAL in near-real-time. If the outbox table
    accumulates rows beyond the threshold, it indicates CDC lag.
    """

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        schema: str,
        *,
        max_backlog: int = 100,
    ) -> None:
        """Initialize the outbox health probe.

        Args:
            session_factory: Callable returning an async context manager for sessions.
            schema: Database schema containing the outbox table.
            max_backlog: Maximum acceptable row count before reporting degraded.

        """
        self.name = "outbox_backlog"
        self._session_factory = session_factory
        self._schema = schema
        self._max_backlog = max_backlog

    async def check(self) -> HealthProbeResult:
        """Execute outbox backlog health check."""
        start = time.perf_counter()
        try:
            async with self._session_factory() as session:
                outbox = Table(
                    "outbox",
                    MetaData(),
                    Column("id", Integer),
                    schema=self._schema,
                )
                result = await session.execute(select(func.count()).select_from(outbox))
                count = result.scalar() or 0

            elapsed_ms = (time.perf_counter() - start) * 1000

            if count > self._max_backlog:
                return HealthProbeResult(
                    name=self.name,
                    status=HealthStatus.DEGRADED,
                    message=f"Outbox backlog: {count} rows (threshold: {self._max_backlog})",
                    latency_ms=elapsed_ms,
                    details={"count": count, "threshold": self._max_backlog},
                )
            return HealthProbeResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"Outbox backlog: {count} rows",
                latency_ms=elapsed_ms,
                details={"count": count, "threshold": self._max_backlog},
            )
        except (OSError, SQLAlchemyError) as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return HealthProbeResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Outbox health check failed: {exc}",
                latency_ms=elapsed_ms,
            )

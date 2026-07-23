"""Database health probe for domain-owned health checking.

Implements the HealthProbe protocol for PostgreSQL connectivity and query execution.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nohiki_common_exceptions import (
    HealthProbeResult,
    HealthProbeTimer,
    create_degraded_result,
    create_healthy_result,
    create_unhealthy_result,
)
from nohiki_observability import get_logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from .migrations import MigrationState

_get_migration_state: Callable[[], MigrationState] | None = None
_HAS_ALEMBIC: bool = False

try:
    from .migrations import get_migration_state as _get_migration_state

    _HAS_ALEMBIC = True
except ImportError:
    pass

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProbeTiming:
    """Timing dependencies for a startup probe retry loop."""

    clock: Callable[[], float] = time.perf_counter
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


class DatabaseHealthProbe:
    """Health probe for PostgreSQL connectivity and query execution.

    Implements the HealthProbe protocol for database health checking.
    Verifies connection pool, query execution, and optionally migration state.
    """

    __slots__ = (
        "_check_migrations",
        "_degraded_threshold_ms",
        "_engine",
        "_timeout_seconds",
    )

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        timeout_seconds: float = 5.0,
        degraded_threshold_ms: float = 100.0,
        check_migrations: bool = True,
    ) -> None:
        """Initialize database health probe.

        Args:
            engine: SQLAlchemy async engine.
            timeout_seconds: Timeout for query execution.
            degraded_threshold_ms: Latency threshold for DEGRADED status.
            check_migrations: If True, also checks migration state.

        """
        self._engine = engine
        self._timeout_seconds = timeout_seconds
        self._degraded_threshold_ms = degraded_threshold_ms
        self._check_migrations = check_migrations

    @property
    def name(self) -> str:
        """Probe identifier."""
        return "database"

    async def check(self) -> HealthProbeResult:
        """Execute database health check.

        Verifies:
        1. Connection pool can provide a connection
        2. SELECT 1 query executes successfully
        3. (Optional) Migration state is healthy
        """
        with HealthProbeTimer() as timer:
            try:
                if self._check_migrations and _HAS_ALEMBIC and _get_migration_state is not None:
                    migration_state = _get_migration_state()
                    if not migration_state.is_healthy():
                        return create_unhealthy_result(
                            name=self.name,
                            message=f"Migrations not completed: {migration_state.status}",
                            latency_ms=timer.elapsed_ms,
                            details=dict(migration_state.to_dict()),
                        )

                async with asyncio.timeout(self._timeout_seconds):
                    async with self._engine.connect() as conn:
                        result = await conn.scalar(select(1))

                        if result != 1:
                            return create_unhealthy_result(
                                name=self.name,
                                message=f"SELECT 1 returned unexpected value: {result}",
                                latency_ms=timer.elapsed_ms,
                            )

            except TimeoutError:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Query timeout after {self._timeout_seconds}s",
                    latency_ms=timer.elapsed_ms,
                )
            except SQLAlchemyError as e:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Database connection failed: {e}",
                    latency_ms=timer.elapsed_ms,
                    details={"error": str(e), "error_type": type(e).__name__},
                )

        return self._evaluate_latency(timer.elapsed_ms)

    def _evaluate_latency(self, latency_ms: float) -> HealthProbeResult:
        """Evaluate latency and return appropriate result."""
        if latency_ms > self._degraded_threshold_ms:
            return create_degraded_result(
                name=self.name,
                message=f"Latency {latency_ms:.2f}ms exceeds degraded threshold {self._degraded_threshold_ms:.2f}ms",
                latency_ms=latency_ms,
            )

        return create_healthy_result(
            name=self.name,
            message="Database is healthy",
            latency_ms=latency_ms,
        )


async def ensure_database_ready(
    engine: AsyncEngine,
    *,
    timeout_seconds: float = 60.0,
    retry_interval_seconds: float = 2.0,
    timing: ProbeTiming | None = None,
) -> None:
    """Block startup until database is available.

    Args:
        engine: SQLAlchemy async engine.
        timeout_seconds: Maximum time to wait for database.
        retry_interval_seconds: Interval between retry attempts.
        timing: Optional timing dependencies for deterministic retry control.

    Raises:
        RuntimeError: If database is unavailable after timeout.

    """
    timing = ProbeTiming() if timing is None else timing
    probe = DatabaseHealthProbe(engine, check_migrations=False)
    start_time = timing.clock()
    attempt = 0

    logger.info(
        "Waiting for database to become available",
        timeout_seconds=timeout_seconds,
    )

    while (timing.clock() - start_time) < timeout_seconds:
        attempt += 1
        result = await probe.check()

        if result.is_healthy():
            elapsed = timing.clock() - start_time
            logger.info(
                "Database is available",
                elapsed_seconds=round(elapsed, 2),
                attempts=attempt,
            )
            return

        remaining = timeout_seconds - (timing.clock() - start_time)
        if remaining > 0:
            wait_time = min(retry_interval_seconds, remaining)
            logger.debug(
                "Database not available, retrying",
                attempt=attempt,
                error=result.message,
                retry_in_seconds=wait_time,
            )
            await timing.sleep(wait_time)

    elapsed = timing.clock() - start_time
    msg = f"Database unavailable after {elapsed:.1f}s ({attempt} attempts)"
    logger.error("Database startup timeout", elapsed_seconds=round(elapsed, 2), attempts=attempt)
    raise RuntimeError(msg)

"""Scheduler processing logic for job-ingest-schedule-service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nohiki_observability import get_logger
from sqlalchemy import select

from job_ingest_schedule_service.db.models import IngestionSchedule
from job_ingest_schedule_service.events.publishers import publish_scrape_triggered

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class InvalidScheduleStateError(RuntimeError):
    """Raised when a selected due schedule violates persistence invariants."""


async def process_due_schedules(
    db: AsyncSession,
    *,
    batch_limit: int,
    now: datetime | None = None,
) -> int:
    """Process all due schedules and publish scrape events.

    Args:
        db: Active database session (caller owns the transaction).
        batch_limit: Maximum number of schedules to process.
        now: Override for current time (testing).

    Returns:
        Number of schedules triggered.
    """
    current_time = now or datetime.now(UTC)

    result = await db.execute(
        select(IngestionSchedule)
        .where(IngestionSchedule.is_active.is_(True))
        .where(IngestionSchedule.next_run_at <= current_time)
        .with_for_update(skip_locked=True)
        .limit(batch_limit)
    )
    due_schedules = list(result.scalars().all())

    if not due_schedules:
        return 0

    for schedule in due_schedules:
        scheduled_for = schedule.next_run_at
        if scheduled_for is None:
            raise InvalidScheduleStateError
        await publish_scrape_triggered(schedule, scheduled_for)
        schedule.last_run_at = current_time
        next_run_at = current_time + schedule.frequency
        schedule.next_run_at = next_run_at
        logger.debug(
            "Published scheduled scrape",
            query_id=str(schedule.query_id),
            next_run_at=next_run_at.isoformat(),
        )

    triggered = len(due_schedules)

    if triggered:
        logger.info("Schedule tick complete", triggered=triggered)
    return triggered

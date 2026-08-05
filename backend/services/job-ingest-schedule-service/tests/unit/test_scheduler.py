"""Unit tests for services/scheduler.py module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki.common.v1 import CountryCode, JobBoardSource, Location, LocationType, WorkArrangement
from nohiki_db_utils.testing import create_mock_session

if TYPE_CHECKING:
    from job_ingest_schedule_service.db.models import IngestionSchedule


def _create_schedule(
    *,
    is_active: bool = True,
    next_run_at: datetime | None = None,
) -> IngestionSchedule:
    """Create a test schedule."""
    from job_ingest_schedule_service.db.models import IngestionSchedule as Schedule

    return Schedule(
        query_id=uuid.uuid4(),
        search_keywords=["python"],
        locations=[
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
            ).to_dict()
        ],
        work_arrangements=[WorkArrangement.REMOTE],
        sources=[JobBoardSource.INDEED],
        hours_old=72,
        results_wanted=50,
        frequency=timedelta(hours=6),
        is_active=is_active,
        next_run_at=next_run_at or datetime.now(UTC) - timedelta(hours=1),
    )


class TestProcessDueSchedules:
    """Behavior contracts for selecting and advancing due schedule runs."""

    @pytest.mark.asyncio
    async def test_publishes_each_due_run_and_advances_each_schedule_once(self) -> None:
        """Every selected due run publishes before its timestamps advance once."""
        from job_ingest_schedule_service.services import scheduler

        now = datetime(2026, 7, 10, 12, tzinfo=UTC)
        first = _create_schedule(next_run_at=now - timedelta(hours=2))
        second = _create_schedule(next_run_at=now - timedelta(hours=1))
        result = MagicMock()
        result.scalars.return_value.all.return_value = [first, second]
        db = create_mock_session()
        db.execute = AsyncMock(return_value=result)
        publish = AsyncMock()

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(scheduler, "publish_scrape_triggered", publish)
            triggered = await scheduler.process_due_schedules(db, batch_limit=100, now=now)

        assert triggered == 2
        assert publish.await_count == 2
        assert [call.args for call in publish.await_args_list] == [
            (first, now - timedelta(hours=2)),
            (second, now - timedelta(hours=1)),
        ]
        for schedule in (first, second):
            assert schedule.last_run_at == now
            assert schedule.next_run_at == now + schedule.frequency

    @pytest.mark.asyncio
    async def test_no_due_schedules_publishes_no_event(self) -> None:
        """An empty due batch neither publishes nor reports a processed run."""
        from job_ingest_schedule_service.services import scheduler

        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db = create_mock_session()
        db.execute = AsyncMock(return_value=result)
        publish = AsyncMock()

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(scheduler, "publish_scrape_triggered", publish)
            triggered = await scheduler.process_due_schedules(db, batch_limit=25)

        assert triggered == 0
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_advance_any_schedule(self) -> None:
        """A publish failure propagates before any schedule timestamp advances."""
        from job_ingest_schedule_service.services import scheduler

        now = datetime(2026, 7, 10, 12, tzinfo=UTC)
        first = _create_schedule(next_run_at=now - timedelta(hours=2))
        second = _create_schedule(next_run_at=now - timedelta(hours=1))
        original_times = [
            (first.last_run_at, first.next_run_at),
            (second.last_run_at, second.next_run_at),
        ]
        result = MagicMock()
        result.scalars.return_value.all.return_value = [first, second]
        db = create_mock_session()
        db.execute = AsyncMock(return_value=result)
        publish = AsyncMock(side_effect=RuntimeError("Kafka unavailable"))

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(scheduler, "publish_scrape_triggered", publish)
            with pytest.raises(RuntimeError, match="Kafka unavailable"):
                await scheduler.process_due_schedules(db, batch_limit=100, now=now)

        assert [(first.last_run_at, first.next_run_at), (second.last_run_at, second.next_run_at)] == original_times
        publish.assert_awaited_once_with(first, original_times[0][1])

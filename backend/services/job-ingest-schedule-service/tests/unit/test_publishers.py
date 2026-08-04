"""Behavior tests for temporary direct schedule-run publication."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from job_ingest_schedule_service.db.models import IngestionSchedule
from nohiki.common.v1 import (
    CountryCode,
    JobBoardSource,
    Location,
    LocationType,
    WorkArrangement,
)


@pytest.fixture
def sample_schedule() -> IngestionSchedule:
    """Create a complete schedule snapshot for the emitted command."""
    return IngestionSchedule(
        query_id=uuid.UUID("35bbaf78-04a0-45e1-ab6c-06fe8206ee53"),
        search_keywords=["python", "developer"],
        locations=[
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
                city="San Francisco",
                state_province="CA",
            ).to_dict()
        ],
        work_arrangements=[WorkArrangement.REMOTE],
        sources=[JobBoardSource.INDEED],
        hours_old=72,
        results_wanted=50,
        frequency=timedelta(hours=6),
        is_active=True,
        next_run_at=datetime(2026, 7, 10, 12, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_publishes_complete_schedule_run_with_deterministic_identity_and_key(
    sample_schedule: IngestionSchedule,
) -> None:
    """A due run has a stable identity/key and carries the complete query command."""
    from job_ingest_schedule_service.events import publishers

    scheduled_for = datetime(2026, 7, 10, 12, tzinfo=UTC)
    kafka = AsyncMock()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(publishers, "kafka_client", kafka)
        await publishers.publish_scrape_triggered(sample_schedule, scheduled_for)

    kafka.publish.assert_awaited_once()
    call = kafka.publish.call_args.kwargs
    expected_run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{sample_schedule.query_id}:{scheduled_for.isoformat()}"))
    assert call["topic"] == publishers.Topics.JOB_INGEST_DISCOVERY_REQUESTED
    assert call["key"] == expected_run_id
    event = call["message"]
    assert event.metadata.correlation_id == expected_run_id
    assert event.query.query_id == str(sample_schedule.query_id)
    assert list(event.query.search_keywords) == ["python", "developer"]
    assert event.query.locations == [
        Location(
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            city="San Francisco",
            state_province="CA",
        )
    ]
    assert list(event.query.work_arrangements) == [WorkArrangement.REMOTE]
    assert list(event.query.sources) == [JobBoardSource.INDEED]
    assert event.query.hours_old == 72
    assert event.query.results_wanted == 50


@pytest.mark.asyncio
async def test_run_identity_is_stable_only_for_the_same_due_run(
    sample_schedule: IngestionSchedule,
) -> None:
    """Retries collide on one run identity while a later run gets a new identity."""
    from job_ingest_schedule_service.events import publishers

    kafka = AsyncMock()
    scheduled_for = datetime(2026, 7, 10, 12, tzinfo=UTC)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(publishers, "kafka_client", kafka)
        await publishers.publish_scrape_triggered(sample_schedule, scheduled_for)
        await publishers.publish_scrape_triggered(sample_schedule, scheduled_for)
        await publishers.publish_scrape_triggered(sample_schedule, scheduled_for + sample_schedule.frequency)

    calls = kafka.publish.await_args_list
    run_ids = [call.kwargs["message"].metadata.correlation_id for call in calls]
    keys = [call.kwargs["key"] for call in calls]
    assert run_ids == keys
    assert run_ids[0] == run_ids[1]
    assert run_ids[2] != run_ids[0]

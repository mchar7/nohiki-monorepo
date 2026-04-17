"""Unit tests for events/handlers.py module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_schedule_service.events.handlers import (
    handle_query_created,
    handle_query_deleted,
    handle_query_updated,
    handle_schedule_tick,
    start_event_consumer,
)
from nohiki.common.v1 import (
    CountryCode,
    EventMetadata,
    JobBoardSource,
    Location,
    LocationType,
    WorkArrangement,
)
from nohiki.job.ingest.v1 import IngestionQueryChanged, IngestionQueryDeleted
from nohiki.sys.v1 import ScheduleTick
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


def _make_context(*, db_session: AsyncMock | None = None) -> MessageContext:
    """Build a message context with the transaction-owned database session."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
    )


def _create_metadata(correlation_id: str | None = None) -> EventMetadata:
    """Create test event metadata."""
    return EventMetadata(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC),
        source_service="test-service",
        correlation_id=correlation_id or str(uuid.uuid4()),
        version="v1",
    )


def _create_query_changed_message(
    query_id: str | None = None,
    *,
    is_active: bool = True,
    frequency_seconds: int = 3600,
) -> IngestionQueryChanged:
    """Create a test IngestionQueryChanged message."""
    return IngestionQueryChanged(
        metadata=_create_metadata(),
        query_id=query_id or str(uuid.uuid4()),
        search_keywords=["python", "developer"],
        locations=[
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
                state_province="CA",
                city="San Francisco",
            )
        ],
        work_arrangements=[WorkArrangement.REMOTE],
        sources=[JobBoardSource.INDEED],
        frequency_seconds=frequency_seconds,
        is_active=is_active,
    )


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_calls_start_consumers(self) -> None:
        """Test that start_event_consumer starts Kafka consumers."""
        from job_ingest_schedule_service.events import handlers

        mock_kafka = MagicMock()
        mock_kafka.start_consumers = MagicMock()

        with patch.object(handlers, "kafka_client", mock_kafka):
            start_event_consumer()
            mock_kafka.start_consumers.assert_called_once()


class TestHandleScheduleTick:
    """Tests for dispatching a bounded due batch."""

    @pytest.mark.asyncio
    async def test_passes_database_and_explicit_batch_limit(self) -> None:
        db = create_mock_session()
        context = _make_context(db_session=db)
        message = ScheduleTick(metadata=_create_metadata(), batch_limit=42)

        with patch(
            "job_ingest_schedule_service.events.handlers.process_due_schedules",
            new_callable=AsyncMock,
            return_value=1,
        ) as process:
            await handle_schedule_tick(message, context)

        process.assert_awaited_once_with(db, batch_limit=42)


class TestHandleQueryCreated:
    """Tests for initial schedule state and its immediate durable dispatch."""

    @pytest.mark.asyncio
    async def test_active_query_creates_schedule_and_publishes_directly(self) -> None:
        message = _create_query_changed_message(is_active=True)
        db = create_mock_session()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()

        with patch(
            "job_ingest_schedule_service.events.handlers.publish_scrape_triggered",
            new_callable=AsyncMock,
        ) as publish:
            await handle_query_created(message, _make_context(db_session=db))

        db.add.assert_called_once()
        schedule = db.add.call_args.args[0]
        assert schedule.query_id == uuid.UUID(message.query_id)
        assert schedule.frequency.total_seconds() == message.frequency_seconds
        assert schedule.is_active is True
        assert schedule.next_run_at is not None
        publish.assert_awaited_once()
        assert publish.await_args is not None
        assert publish.await_args.args[0] is schedule

    @pytest.mark.asyncio
    async def test_inactive_query_creates_no_dispatch_event(self) -> None:
        message = _create_query_changed_message(is_active=False)
        db = create_mock_session()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()
        with patch(
            "job_ingest_schedule_service.events.handlers.publish_scrape_triggered",
            new_callable=AsyncMock,
        ) as publish:
            await handle_query_created(message, _make_context(db_session=db))

        schedule = db.add.call_args.args[0]
        assert schedule.next_run_at is None
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_existing_schedule_is_idempotent(self) -> None:
        message = _create_query_changed_message()
        db = create_mock_session()
        db.get = AsyncMock(return_value=MagicMock())
        db.add = MagicMock()
        with patch(
            "job_ingest_schedule_service.events.handlers.publish_scrape_triggered",
            new_callable=AsyncMock,
        ) as publish:
            await handle_query_created(message, _make_context(db_session=db))

        db.add.assert_not_called()
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("frequency_seconds", [0, -1])
    async def test_rejects_non_positive_interval_without_state_or_event(
        self,
        frequency_seconds: int,
    ) -> None:
        from job_ingest_schedule_service.events.handlers import InvalidScheduleFrequencyError

        message = _create_query_changed_message(frequency_seconds=frequency_seconds)
        db = create_mock_session()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()
        with (
            patch(
                "job_ingest_schedule_service.events.handlers.publish_scrape_triggered",
                new_callable=AsyncMock,
            ) as publish,
            pytest.raises(InvalidScheduleFrequencyError),
        ):
            await handle_query_created(message, _make_context(db_session=db))

        db.add.assert_not_called()
        publish.assert_not_awaited()


class TestHandleQueryUpdated:
    """Tests for schedule changes, including immediate activation runs."""

    @pytest.mark.asyncio
    async def test_lone_existing_update_is_applied_immediately(self) -> None:
        message = _create_query_changed_message(is_active=True, frequency_seconds=7200)
        schedule = MagicMock()
        schedule.is_active = True
        schedule.next_run_at = datetime.now(UTC)
        db = create_mock_session()
        db.get = AsyncMock(return_value=schedule)
        with patch(
            "job_ingest_schedule_service.events.handlers.publish_scrape_triggered",
            new_callable=AsyncMock,
        ) as publish:
            await handle_query_updated(message, _make_context(db_session=db))

        assert schedule.search_keywords == ["python", "developer"]
        assert schedule.frequency.total_seconds() == 7200
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_activation_advances_next_run_and_queues_immediate_event(self) -> None:
        message = _create_query_changed_message(is_active=True, frequency_seconds=3600)
        schedule = MagicMock()
        schedule.is_active = False
        schedule.next_run_at = None
        db = create_mock_session()
        db.get = AsyncMock(return_value=schedule)
        before = datetime.now(UTC)
        with patch(
            "job_ingest_schedule_service.events.handlers.publish_scrape_triggered",
            new_callable=AsyncMock,
        ) as publish:
            await handle_query_updated(message, _make_context(db_session=db))

        after = datetime.now(UTC)
        next_run_at = schedule.next_run_at
        assert next_run_at is not None
        assert before.replace(microsecond=0) <= next_run_at <= after + schedule.frequency
        assert schedule.is_active is True
        publish.assert_awaited_once()
        assert publish.await_args is not None
        assert publish.await_args.args[0] is schedule

    @pytest.mark.asyncio
    async def test_out_of_order_active_update_creates_schedule_and_event(self) -> None:
        message = _create_query_changed_message(is_active=True)
        db = create_mock_session()
        db.get = AsyncMock(return_value=None)
        db.add = MagicMock()
        with patch(
            "job_ingest_schedule_service.events.handlers.publish_scrape_triggered",
            new_callable=AsyncMock,
        ) as publish:
            await handle_query_updated(message, _make_context(db_session=db))

        schedule = db.add.call_args.args[0]
        assert schedule.query_id == uuid.UUID(message.query_id)
        assert schedule.next_run_at is not None
        publish.assert_awaited_once()
        assert publish.await_args is not None
        assert publish.await_args.args[0] is schedule


class TestHandleQueryDeleted:
    """Tests for handle_query_deleted handler."""

    @pytest.mark.asyncio
    async def test_deletes_existing_schedule(self) -> None:
        """Test that handler deletes an existing schedule."""
        query_id = str(uuid.uuid4())
        message = IngestionQueryDeleted(
            metadata=_create_metadata(),
            query_id=query_id,
        )

        existing_schedule = MagicMock()

        mock_db = create_mock_session()
        mock_db.get = AsyncMock(return_value=existing_schedule)
        mock_db.delete = AsyncMock()
        context = _make_context(db_session=mock_db)

        await handle_query_deleted(message, context)

        mock_db.delete.assert_awaited_once_with(existing_schedule)

    @pytest.mark.asyncio
    async def test_skips_if_not_found(self) -> None:
        """Test that handler skips if schedule not found (idempotency)."""
        message = IngestionQueryDeleted(
            metadata=_create_metadata(),
            query_id=str(uuid.uuid4()),
        )

        mock_db = create_mock_session()
        mock_db.get = AsyncMock(return_value=None)
        mock_db.delete = AsyncMock()
        context = _make_context(db_session=mock_db)

        await handle_query_deleted(message, context)

        mock_db.delete.assert_not_called()

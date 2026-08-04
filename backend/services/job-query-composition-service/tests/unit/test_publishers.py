"""Unit tests for event publishers."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from job_query_composition_service.db.models import IngestionQuery as DBIngestionQuery
from job_query_composition_service.events.publishers import (
    publish_queries_updated_batch,
    publish_query_created,
    publish_query_deleted,
    publish_query_deleted_batch,
    publish_query_updated,
)
from nohiki.common.v1 import CountryCode, Location, LocationType
from nohiki.job.ingest.v1 import IngestionQueryChanged, IngestionQueryDeleted
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import Topics


class TestPublishQueryCreated:
    @pytest.mark.asyncio
    async def test_publishes_correct_event(self) -> None:
        """Test that publish_query_created publishes to JOB_QUERY_CREATED topic."""
        mock_query = MagicMock(spec=DBIngestionQuery)
        mock_query.id = uuid4()
        mock_query.search_keywords = ["python", "developer"]
        mock_query.locations = [
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
                city="NYC",
                state_province="NY",
            ).to_dict()
        ]
        mock_query.work_arrangements = ["remote"]
        mock_query.sources = ["linkedin"]
        mock_query.frequency = timedelta(hours=24)
        mock_query.is_active = True

        mock_db = create_mock_session()
        mock_outbox = AsyncMock()

        with patch(
            "job_query_composition_service.events.publishers.get_settings",
            return_value=MagicMock(service_name="job-query-composition-service"),
        ):
            await publish_query_created(mock_db, mock_outbox, mock_query)

        mock_outbox.write_event.assert_called_once()
        call_args = mock_outbox.write_event.call_args
        assert call_args.kwargs["params"].event_type == Topics.JOB_QUERY_CREATED
        event = call_args.kwargs["event"]
        assert isinstance(event, IngestionQueryChanged)
        assert event.query_id == str(mock_query.id)
        assert event.frequency_seconds == 86400
        assert event.is_active is True
        assert len(event.locations) == 1
        assert isinstance(event.locations[0], Location)
        assert event.locations[0].country == CountryCode.USA
        assert event.locations[0].city == "NYC"

    @pytest.mark.asyncio
    async def test_rejects_legacy_single_location_object(self) -> None:
        """A bare location object is not accepted as canonical list storage."""
        mock_query = _make_mock_query()
        mock_query.locations = mock_query.locations[0]
        mock_outbox = AsyncMock()

        with pytest.raises(AttributeError):
            await publish_query_created(create_mock_session(), mock_outbox, mock_query)

        mock_outbox.write_event.assert_not_awaited()


def _make_mock_query() -> MagicMock:
    """Create a mock DBIngestionQuery for publisher tests."""
    mock_query = MagicMock(spec=DBIngestionQuery)
    mock_query.id = uuid4()
    mock_query.search_keywords = ["python"]
    mock_query.locations = [
        Location(
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            city="NYC",
            state_province="NY",
        ).to_dict()
    ]
    mock_query.work_arrangements = ["remote"]
    mock_query.sources = ["linkedin"]
    mock_query.frequency = timedelta(hours=24)
    mock_query.is_active = True
    return mock_query


class TestPublishQueryUpdated:
    """Tests for publish_query_updated function."""

    @pytest.mark.asyncio
    async def test_publishes_updated_event(self) -> None:
        """Publish_query_updated writes to outbox with JOB_QUERY_UPDATED topic."""
        mock_query = _make_mock_query()
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()

        with patch(
            "job_query_composition_service.events.publishers.get_settings",
            return_value=MagicMock(service_name="job-query-composition-service"),
        ):
            await publish_query_updated(mock_db, mock_outbox, mock_query)

        mock_outbox.write_event.assert_called_once()
        call_args = mock_outbox.write_event.call_args
        assert call_args.kwargs["params"].event_type == Topics.JOB_QUERY_UPDATED
        event = call_args.kwargs["event"]
        assert isinstance(event, IngestionQueryChanged)
        assert event.query_id == str(mock_query.id)


class TestPublishQueryDeleted:
    """Tests for publish_query_deleted function."""

    @pytest.mark.asyncio
    async def test_publishes_deleted_event(self) -> None:
        """Publish_query_deleted writes to outbox with JOB_QUERY_DELETED topic."""
        query_id = uuid4()
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()

        with patch(
            "job_query_composition_service.events.publishers.get_settings",
            return_value=MagicMock(service_name="job-query-composition-service"),
        ):
            await publish_query_deleted(mock_db, mock_outbox, query_id)

        mock_outbox.write_event.assert_called_once()
        call_args = mock_outbox.write_event.call_args
        assert call_args.kwargs["params"].event_type == Topics.JOB_QUERY_DELETED
        event = call_args.kwargs["event"]
        assert isinstance(event, IngestionQueryDeleted)
        assert event.query_id == str(query_id)


class TestPublishQueriesUpdatedBatch:
    """Tests for publish_queries_updated_batch function."""

    @pytest.mark.asyncio
    async def test_publishes_batch(self) -> None:
        """Publish_queries_updated_batch publishes for each query."""
        queries = [_make_mock_query(), _make_mock_query()]
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_events = AsyncMock()

        with patch(
            "job_query_composition_service.events.publishers.get_settings",
            return_value=MagicMock(service_name="job-query-composition-service"),
        ):
            await publish_queries_updated_batch(mock_db, mock_outbox, queries)

        mock_outbox.write_events.assert_awaited_once()
        assert len(mock_outbox.write_events.call_args.kwargs["entries"]) == 2


class TestPublishQueryDeletedBatch:
    """Tests for publish_query_deleted_batch function."""

    @pytest.mark.asyncio
    async def test_publishes_batch(self) -> None:
        """Publish_query_deleted_batch publishes for each query id."""
        query_ids = [uuid4(), uuid4()]
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_events = AsyncMock()

        with patch(
            "job_query_composition_service.events.publishers.get_settings",
            return_value=MagicMock(service_name="job-query-composition-service"),
        ):
            await publish_query_deleted_batch(mock_db, mock_outbox, query_ids)

        mock_outbox.write_events.assert_awaited_once()
        assert len(mock_outbox.write_events.call_args.kwargs["entries"]) == 2

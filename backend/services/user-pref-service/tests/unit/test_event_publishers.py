"""Unit tests for profile_service.events.publishers module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.common.v1 import EntityTimestamps
from nohiki.user.pref.v1 import (
    PrefCreated,
    PrefDeleted,
    PrefEnrichmentFailed,
    PrefEnrichmentFailedFailureReason,
    PrefUpdated,
    SearchPrefSnapshot,
)
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import Topics
from user_pref_service.db.models import SearchPref
from user_pref_service.events.publishers import (
    AGGREGATE_TYPE,
    publish_pref_command_rejected,
    publish_profile_created_event,
    publish_profile_deleted_event,
    publish_profile_updated_batch,
    publish_profile_updated_event,
)


class TestPublishProfileCreatedEvent:
    """Tests for publish_profile_created_event function."""

    @pytest.mark.asyncio
    async def test_publishes_created_event_with_snapshot(self) -> None:
        """Publishes profile.created.v1 event with ProfileSnapshot."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event = AsyncMock(return_value=uuid.uuid4())

        correlation_id = str(uuid.uuid4())
        profile = MagicMock(spec=SearchPref)
        profile.id = uuid.uuid4()
        profile.user_id = uuid.uuid4()
        profile.profile_name = "Test Profile"
        profile.search_keywords = ["python"]
        profile.disallowed_keywords = []
        profile.physical_locations = None
        profile.remote_locations = None
        profile.work_arrangements = []
        profile.excluded_job_board_sources = []
        profile.min_fit_score_disqualify = None
        profile.notification_threshold = 70
        profile.auto_tailor_threshold = None
        profile.tailoring_schema_id = None
        profile.tailoring_preferences = {}
        profile.is_active = True
        profile.attachments = []
        profile.created_at = datetime.now(UTC)
        profile.updated_at = datetime.now(UTC)

        mock_snapshot = SearchPrefSnapshot(
            id=str(profile.id),
            user_id=str(profile.user_id),
            pref_name="Test Profile",
            search_keywords=["python"],
            is_active=True,
            timestamps=EntityTimestamps(created_at=datetime.now(UTC), updated_at=datetime.now(UTC)),
        )

        with (
            patch(
                "user_pref_service.events.publishers.build_profile_snapshot",
                return_value=mock_snapshot,
            ),
            patch(
                "user_pref_service.events.publishers.get_profile_by_id",
                new_callable=AsyncMock,
                return_value=profile,
            ),
        ):
            await publish_profile_created_event(mock_db, mock_outbox, profile, correlation_id=correlation_id)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs

        assert call_kwargs["db"] == mock_db
        assert call_kwargs["params"].aggregate_type == AGGREGATE_TYPE
        assert call_kwargs["params"].aggregate_id == str(profile.id)
        assert call_kwargs["params"].event_type == Topics.USER_PREF_CREATED

        event = call_kwargs["event"]
        assert isinstance(event, PrefCreated)
        assert event.pref_id == str(profile.id)
        assert event.user_id == str(profile.user_id)
        assert event.pref_snapshot == mock_snapshot
        assert event.metadata.correlation_id == correlation_id


class TestPublishProfileUpdatedEvent:
    """Tests for publish_profile_updated_event function."""

    @pytest.mark.asyncio
    async def test_publishes_updated_event_with_snapshot(self) -> None:
        """Publishes profile.updated.v1 event with ProfileSnapshot."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event = AsyncMock(return_value=uuid.uuid4())

        correlation_id = str(uuid.uuid4())
        profile = MagicMock(spec=SearchPref)
        profile.id = uuid.uuid4()
        profile.user_id = uuid.uuid4()
        profile.profile_name = "Updated Profile"
        profile.search_keywords = ["python", "fastapi"]
        profile.disallowed_keywords = []
        profile.physical_locations = None
        profile.remote_locations = None
        profile.work_arrangements = []
        profile.excluded_job_board_sources = []
        profile.min_fit_score_disqualify = None
        profile.notification_threshold = 80
        profile.auto_tailor_threshold = None
        profile.tailoring_schema_id = None
        profile.tailoring_preferences = {}
        profile.is_active = True
        profile.attachments = []
        profile.created_at = datetime.now(UTC)
        profile.updated_at = datetime.now(UTC)

        mock_snapshot = SearchPrefSnapshot(
            id=str(profile.id),
            user_id=str(profile.user_id),
            pref_name="Updated Profile",
            search_keywords=["python", "fastapi"],
            is_active=True,
            timestamps=EntityTimestamps(created_at=datetime.now(UTC), updated_at=datetime.now(UTC)),
        )

        with (
            patch(
                "user_pref_service.events.publishers.build_profile_snapshot",
                return_value=mock_snapshot,
            ),
            patch(
                "user_pref_service.events.publishers.get_profile_by_id",
                new_callable=AsyncMock,
                return_value=profile,
            ),
        ):
            await publish_profile_updated_event(mock_db, mock_outbox, profile, correlation_id=correlation_id)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs

        assert call_kwargs["params"].event_type == Topics.USER_PREF_UPDATED

        event = call_kwargs["event"]
        assert isinstance(event, PrefUpdated)
        assert event.pref_id == str(profile.id)
        assert event.user_id == str(profile.user_id)
        assert event.pref_snapshot == mock_snapshot
        assert event.metadata.correlation_id == correlation_id


class TestPublishProfileUpdatedBatch:
    """Tests for publish_profile_updated_batch function."""

    @pytest.mark.asyncio
    async def test_publishes_batch(self) -> None:
        """Publishes profile.updated.v1 events with a single batch outbox write."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_events = AsyncMock(return_value=[])

        profile_1 = MagicMock(spec=SearchPref)
        profile_1.id = uuid.uuid4()
        profile_1.user_id = uuid.uuid4()
        profile_1.search_keywords = []
        profile_1.disallowed_keywords = []
        profile_1.physical_locations = []
        profile_1.remote_locations = []
        profile_1.work_arrangements = []
        profile_1.open_to_relocation = False
        profile_1.commute_preferences = None
        profile_1.experience_years = None
        profile_1.seniority_levels = []
        profile_1.salary_preference = None
        profile_1.feature_importance = None
        profile_1.excluded_scrape_sources = []
        profile_1.min_fit_score_disqualify = None
        profile_1.auto_tailor_threshold = None
        profile_1.tailoring_schema_id = None
        profile_1.tailoring_preferences = None
        profile_1.notification_config = None
        profile_1.is_active = True
        profile_1.user_skill_ids = []
        profile_1.user_skills_data = None
        profile_1.user_skills_embedding = None
        profile_1.query_embedding = None
        profile_1.query_artifacts_data = None
        profile_1.collection_version = None
        profile_1.is_enrichment_complete = False
        profile_1.attachments = []
        profile_1.created_at = datetime.now(UTC)
        profile_1.updated_at = datetime.now(UTC)

        profile_2 = MagicMock(spec=SearchPref)
        profile_2.id = uuid.uuid4()
        profile_2.user_id = uuid.uuid4()
        profile_2.search_keywords = []
        profile_2.disallowed_keywords = []
        profile_2.physical_locations = []
        profile_2.remote_locations = []
        profile_2.work_arrangements = []
        profile_2.open_to_relocation = False
        profile_2.commute_preferences = None
        profile_2.experience_years = None
        profile_2.seniority_levels = []
        profile_2.salary_preference = None
        profile_2.feature_importance = None
        profile_2.excluded_scrape_sources = []
        profile_2.min_fit_score_disqualify = None
        profile_2.auto_tailor_threshold = None
        profile_2.tailoring_schema_id = None
        profile_2.tailoring_preferences = None
        profile_2.notification_config = None
        profile_2.is_active = True
        profile_2.user_skill_ids = []
        profile_2.user_skills_data = None
        profile_2.user_skills_embedding = None
        profile_2.query_embedding = None
        profile_2.query_artifacts_data = None
        profile_2.collection_version = None
        profile_2.is_enrichment_complete = False
        profile_2.attachments = []
        profile_2.created_at = datetime.now(UTC)
        profile_2.updated_at = datetime.now(UTC)

        with patch(
            "user_pref_service.events.publishers.build_profile_snapshot",
            return_value=SearchPrefSnapshot(
                id=str(profile_1.id),
                user_id=str(profile_1.user_id),
                pref_name="Test Profile",
                search_keywords=["python"],
                is_active=True,
                timestamps=EntityTimestamps(created_at=datetime.now(UTC), updated_at=datetime.now(UTC)),
            ),
        ):
            await publish_profile_updated_batch(mock_db, mock_outbox, [profile_1, profile_2])

        mock_outbox.write_events.assert_awaited_once()
        call_kwargs = mock_outbox.write_events.call_args.kwargs
        assert call_kwargs["db"] == mock_db
        assert len(call_kwargs["entries"]) == 2


class TestPublishProfileDeletedEvent:
    """Tests for publish_profile_deleted_event function."""

    @pytest.mark.asyncio
    async def test_publishes_deleted_event(self) -> None:
        """Publishes profile.deleted.v1 event with IDs only."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event = AsyncMock(return_value=uuid.uuid4())

        pref_id = uuid.uuid4()
        user_id = uuid.uuid4()

        await publish_profile_deleted_event(mock_db, mock_outbox, pref_id, user_id)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs

        assert call_kwargs["db"] == mock_db
        assert call_kwargs["params"].aggregate_type == AGGREGATE_TYPE
        assert call_kwargs["params"].aggregate_id == str(pref_id)
        assert call_kwargs["params"].event_type == Topics.USER_PREF_DELETED

        event = call_kwargs["event"]
        assert isinstance(event, PrefDeleted)
        assert event.pref_id == str(pref_id)
        assert event.user_id == str(user_id)


class TestPublishPrefCommandRejected:
    @pytest.mark.asyncio
    async def test_publishes_correlated_terminal_rejection(self) -> None:
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        pref_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request_id = uuid.uuid4()
        correlation_id = str(request_id)
        message = MagicMock(
            pref_id=str(pref_id),
            user_id=str(user_id),
            request_id=str(request_id),
        )
        message.metadata.correlation_id = correlation_id

        await publish_pref_command_rejected(
            mock_db,
            mock_outbox,
            message,
            error_message="Profile unavailable",
        )

        mock_outbox.write_event.assert_awaited_once()
        event = mock_outbox.write_event.await_args.kwargs["event"]
        assert isinstance(event, PrefEnrichmentFailed)
        assert event.reason == PrefEnrichmentFailedFailureReason.REJECTED
        assert event.request_id == str(request_id)
        assert event.metadata.correlation_id == correlation_id


class TestEventConstants:
    """Tests for event topic constants."""

    def test_topic_names(self) -> None:
        """Verifies topic name constants."""
        assert Topics.USER_PREF_CREATED == "user-pref.cdc.pref-created.v1"
        assert Topics.USER_PREF_UPDATED == "user-pref.cdc.pref-updated.v1"
        assert Topics.USER_PREF_DELETED == "user-pref.cdc.pref-deleted.v1"

    def test_aggregate_type(self) -> None:
        """Verifies aggregate type constant."""
        assert AGGREGATE_TYPE == "profile"

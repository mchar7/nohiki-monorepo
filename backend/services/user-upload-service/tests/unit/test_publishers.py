"""Unit tests for attachment_service.events.publishers module.

NOTE: Publishers now use protobuf messages instead of raw JSON.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import Topics
from user_upload_service.db.models import Upload
from user_upload_service.events.publishers import (
    AGGREGATE_TYPE,
    publish_attachment_created_event,
    publish_attachment_deleted_batch,
    publish_attachment_deleted_event,
)


@pytest.fixture
def sample_attachment() -> MagicMock:
    """Create a sample attachment for testing."""
    attachment = MagicMock(spec=Upload)
    attachment.id = uuid.uuid4()
    attachment.user_id = uuid.uuid4()
    attachment.name = "resume.pdf"
    attachment.content_type = "application/pdf"
    attachment.content_hash = "abc123def456"
    attachment.file_size = 2048
    attachment.storage_key = f"{attachment.user_id}/{attachment.content_hash}/resume.pdf"
    attachment.created_at = datetime.now(UTC)
    attachment.updated_at = datetime.now(UTC)
    return attachment


class TestPublishAttachmentCreatedEvent:
    """Tests for publish_attachment_created_event function."""

    @pytest.mark.asyncio
    async def test_publishes_created_event(self, sample_attachment: MagicMock) -> None:
        """Publishes upload.created.v1 event via outbox with protobuf."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event = AsyncMock()

        await publish_attachment_created_event(mock_db, mock_outbox, sample_attachment)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs

        assert call_kwargs["db"] == mock_db
        assert call_kwargs["params"].event_type == Topics.USER_UPLOAD_CREATED

        # Verify event is a protobuf message
        event = call_kwargs["event"]
        assert event.upload_id == str(sample_attachment.id)
        assert event.user_id == str(sample_attachment.user_id)


class TestPublishAttachmentDeletedEvent:
    """Tests for publish_attachment_deleted_event function."""

    @pytest.mark.asyncio
    async def test_publishes_deleted_event(self) -> None:
        """Publishes upload.deleted.v1 event via outbox with protobuf."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event = AsyncMock()

        upload_id = uuid.uuid4()
        user_id = uuid.uuid4()

        await publish_attachment_deleted_event(mock_db, mock_outbox, upload_id, user_id)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs

        assert call_kwargs["params"].event_type == Topics.USER_UPLOAD_DELETED

        event = call_kwargs["event"]
        assert event.upload_id == str(upload_id)
        assert event.user_id == str(user_id)


class TestPublishAttachmentDeletedBatch:
    """Tests for publish_attachment_deleted_batch function."""

    @pytest.mark.asyncio
    async def test_publishes_batch(self) -> None:
        """Publishes deleted events with a single batch outbox write."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_events = AsyncMock()

        attachments = []
        for _ in range(2):
            attachment = MagicMock(spec=Upload)
            attachment.id = uuid.uuid4()
            attachment.user_id = uuid.uuid4()
            attachments.append(attachment)

        await publish_attachment_deleted_batch(mock_db, mock_outbox, attachments)

        mock_outbox.write_events.assert_awaited_once()
        call_kwargs = mock_outbox.write_events.call_args.kwargs
        assert call_kwargs["db"] == mock_db
        assert len(call_kwargs["entries"]) == 2


class TestBuildUploadSnapshot:
    """Tests for _build_upload_snapshot helper."""

    def test_raises_when_timestamps_are_none(self) -> None:
        """Raises ValueError when created_at or updated_at is None."""
        from user_upload_service.events.publishers import _build_upload_snapshot

        attachment = MagicMock(spec=Upload)
        attachment.created_at = None
        attachment.updated_at = None

        with pytest.raises(ValueError, match="created_at and updated_at must be set"):
            _build_upload_snapshot(attachment)

    def test_adds_utc_to_naive_created_at(self) -> None:
        """Adds UTC tzinfo to timezone-naive created_at."""
        from user_upload_service.events.publishers import _build_upload_snapshot

        attachment = MagicMock(spec=Upload)
        attachment.id = uuid.uuid4()
        attachment.user_id = uuid.uuid4()
        attachment.name = "test.pdf"
        attachment.content_type = "application/pdf"
        attachment.content_hash = "abc"
        attachment.file_size = 100
        attachment.storage_key = "key"
        attachment.created_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)
        attachment.updated_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        snapshot = _build_upload_snapshot(attachment)

        assert snapshot.timestamps is not None
        assert snapshot.timestamps.created_at is not None
        assert snapshot.timestamps.created_at.tzinfo == UTC

    def test_adds_utc_to_naive_updated_at(self) -> None:
        """Adds UTC tzinfo to timezone-naive updated_at."""
        from user_upload_service.events.publishers import _build_upload_snapshot

        attachment = MagicMock(spec=Upload)
        attachment.id = uuid.uuid4()
        attachment.user_id = uuid.uuid4()
        attachment.name = "test.pdf"
        attachment.content_type = "application/pdf"
        attachment.content_hash = "abc"
        attachment.file_size = 100
        attachment.storage_key = "key"
        attachment.created_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        attachment.updated_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)

        snapshot = _build_upload_snapshot(attachment)

        assert snapshot.timestamps is not None
        assert snapshot.timestamps.updated_at is not None
        assert snapshot.timestamps.updated_at.tzinfo == UTC


class TestAggregateType:
    """Tests for aggregate type constant."""

    def test_aggregate_type(self) -> None:
        """Verifies aggregate type constant value."""
        assert AGGREGATE_TYPE == "upload"

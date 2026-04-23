"""Tests for notification event publisher using outbox pattern."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.common.v1 import NotificationChannel
from notification_service.db.models import Message, MessageStatus
from notification_service.services.outbox.event_publisher import NotificationEventPublisher


class TestPublishSent:
    """Tests for publish_sent method with outbox pattern."""

    @pytest.fixture
    def publisher(self) -> NotificationEventPublisher:
        """Provide a NotificationEventPublisher instance."""
        return NotificationEventPublisher()

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Provide a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def sent_message(self) -> MagicMock:
        """Provide a mock sent message."""
        msg = MagicMock(spec=Message)
        msg.id = uuid4()
        msg.correlation_id = uuid4()
        msg.user_id = uuid4()
        msg.stored_listing_id = uuid4()
        msg.recipient = "test@example.com"
        msg.subject = "Test Subject"
        msg.provider_name = "resend"
        msg.provider_msg_id = "msg_12345"
        msg.priority = 1
        msg.retry_count = 0
        msg.sent_at = datetime.now(UTC)
        msg.scheduled_at = None
        msg.channel = MagicMock()
        msg.channel.to_proto.return_value = NotificationChannel.EMAIL
        return msg

    @pytest.mark.asyncio
    async def test_publish_sent_success(
        self,
        publisher: NotificationEventPublisher,
        mock_db: AsyncMock,
        sent_message: MagicMock,
    ) -> None:
        """Successful publish writes to outbox."""
        with patch("notification_service.services.outbox.event_publisher.OutboxWriter") as mock_outbox_class:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_class.return_value = mock_outbox

            await publisher.publish_sent(mock_db, sent_message)

            mock_outbox.write_event.assert_awaited_once()
            call_kwargs = mock_outbox.write_event.call_args.kwargs
            assert call_kwargs["db"] is mock_db
            assert "params" in call_kwargs
            assert "event" in call_kwargs

    @pytest.mark.asyncio
    async def test_publish_sent_includes_scheduled_at(
        self,
        publisher: NotificationEventPublisher,
        mock_db: AsyncMock,
        sent_message: MagicMock,
    ) -> None:
        """Published event includes scheduled_at if present."""
        sent_message.scheduled_at = datetime.now(UTC)

        with patch("notification_service.services.outbox.event_publisher.OutboxWriter") as mock_outbox_class:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_class.return_value = mock_outbox

            await publisher.publish_sent(mock_db, sent_message)

            call_kwargs = mock_outbox.write_event.call_args.kwargs
            event = call_kwargs["event"]
            assert event.scheduled_at is not None

    @pytest.mark.asyncio
    async def test_publish_sent_with_naive_datetime(
        self,
        publisher: NotificationEventPublisher,
        mock_db: AsyncMock,
        sent_message: MagicMock,
    ) -> None:
        """Naive datetime is converted to UTC."""
        sent_message.sent_at = datetime.now()
        sent_message.scheduled_at = datetime.now()

        with patch("notification_service.services.outbox.event_publisher.OutboxWriter") as mock_outbox_class:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_class.return_value = mock_outbox

            await publisher.publish_sent(mock_db, sent_message)

            mock_outbox.write_event.assert_awaited_once()


class TestPublishFailed:
    """Tests for publish_failed method with outbox pattern."""

    @pytest.fixture
    def publisher(self) -> NotificationEventPublisher:
        """Provide a NotificationEventPublisher instance."""
        return NotificationEventPublisher()

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Provide a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def failed_message(self) -> MagicMock:
        """Provide a mock failed message."""
        msg = MagicMock(spec=Message)
        msg.id = uuid4()
        msg.correlation_id = uuid4()
        msg.user_id = uuid4()
        msg.stored_listing_id = uuid4()
        msg.recipient = "test@example.com"
        msg.subject = "Test Subject"
        msg.provider_name = "resend"
        msg.priority = 1
        msg.retry_count = 3
        msg.last_error = "Rate limit exceeded"
        msg.status = MessageStatus.FAILED
        msg.scheduled_at = None
        msg.retry_at = None
        msg.channel = MagicMock()
        msg.channel.to_proto.return_value = NotificationChannel.EMAIL
        return msg

    @pytest.mark.asyncio
    async def test_publish_failed_success(
        self,
        publisher: NotificationEventPublisher,
        mock_db: AsyncMock,
        failed_message: MagicMock,
    ) -> None:
        """Successful publish writes to outbox."""
        with patch("notification_service.services.outbox.event_publisher.OutboxWriter") as mock_outbox_class:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_class.return_value = mock_outbox

            await publisher.publish_failed(mock_db, failed_message)

            mock_outbox.write_event.assert_awaited_once()
            call_kwargs = mock_outbox.write_event.call_args.kwargs
            assert call_kwargs["db"] is mock_db
            assert "params" in call_kwargs
            assert "event" in call_kwargs

    @pytest.mark.asyncio
    async def test_publish_failed_will_retry_true(
        self,
        publisher: NotificationEventPublisher,
        mock_db: AsyncMock,
        failed_message: MagicMock,
    ) -> None:
        """will_retry is True when status is RETRYING with retry_at."""
        failed_message.status = MessageStatus.RETRYING
        failed_message.retry_at = datetime.now(UTC)

        with patch("notification_service.services.outbox.event_publisher.OutboxWriter") as mock_outbox_class:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_class.return_value = mock_outbox

            await publisher.publish_failed(mock_db, failed_message)

            call_kwargs = mock_outbox.write_event.call_args.kwargs
            event = call_kwargs["event"]
            assert event.will_retry is True

    @pytest.mark.asyncio
    async def test_publish_failed_will_retry_false(
        self,
        publisher: NotificationEventPublisher,
        mock_db: AsyncMock,
        failed_message: MagicMock,
    ) -> None:
        """will_retry is False when status is FAILED."""
        failed_message.status = MessageStatus.FAILED
        failed_message.retry_at = None

        with patch("notification_service.services.outbox.event_publisher.OutboxWriter") as mock_outbox_class:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_class.return_value = mock_outbox

            await publisher.publish_failed(mock_db, failed_message)

            call_kwargs = mock_outbox.write_event.call_args.kwargs
            event = call_kwargs["event"]
            assert event.will_retry is False

    @pytest.mark.asyncio
    async def test_publish_failed_includes_failure_cause(
        self,
        publisher: NotificationEventPublisher,
        mock_db: AsyncMock,
        failed_message: MagicMock,
    ) -> None:
        """Published event includes determined failure cause."""
        failed_message.last_error = "rate limit exceeded"

        with patch("notification_service.services.outbox.event_publisher.OutboxWriter") as mock_outbox_class:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_class.return_value = mock_outbox

            await publisher.publish_failed(mock_db, failed_message)

            call_kwargs = mock_outbox.write_event.call_args.kwargs
            event = call_kwargs["event"]
            assert event.failure_cause is not None

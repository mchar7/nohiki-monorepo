"""Tests for MessageRepository CRUD operations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.common.v1 import NotificationChannel
from nohiki_db_utils.testing import create_mock_session
from nohiki_fastapi_utils.errors import ErrorCode, NohikiError
from nohiki_proto_google.protobuf import Struct
from notification_service.db.models import Message, MessageStatus
from notification_service.services.messaging.repository import MessageRepository
from notification_service.services.schemas import MessageCreate, MessageQueryParams, MessageUpdate
from sqlalchemy.exc import IntegrityError


class TestEnqueueRenderRequest:
    """Tests for _enqueue_render_request helper function."""

    @pytest.mark.asyncio
    async def test_missing_layout_id_raises(self) -> None:
        """Missing external_layout_id raises validation error."""
        from notification_service.services.messaging.repository import _enqueue_render_request

        mock_message = MagicMock(spec=Message)
        mock_message.external_layout_id = None
        mock_db = create_mock_session()

        with pytest.raises(NohikiError) as exc_info:
            await _enqueue_render_request(mock_db, mock_message, {})

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR
        assert "external_layout_id is required" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_successful_enqueue(self) -> None:
        """Successful enqueue writes the event transactionally and updates message state."""
        from notification_service.services.messaging.repository import _enqueue_render_request

        mock_db = create_mock_session()
        mock_message = MagicMock(spec=Message)
        mock_message.id = uuid4()
        mock_message.external_layout_id = uuid4()
        mock_message.external_layout_version = "2.3.4-rc.1+build.7"
        mock_message.external_layout_content = "<html>{{ subject }}</html>"
        mock_message.correlation_id = None
        writer = MagicMock()
        writer.write_event = AsyncMock()

        with patch(
            "notification_service.services.messaging.repository.OutboxWriter",
            return_value=writer,
        ):
            await _enqueue_render_request(mock_db, mock_message, {"key": "value"})

        writer.write_event.assert_awaited_once()
        write_call = writer.write_event.await_args
        assert write_call is not None
        event = write_call.kwargs["event"]
        assert event.template_id == str(mock_message.external_layout_id)
        assert event.template_version == "2.3.4-rc.1+build.7"
        assert event.template_content == "<html>{{ subject }}</html>"
        assert event.data == Struct.from_dict({"key": "value"})
        assert mock_message.status == MessageStatus.WAITING_FOR_RENDER
        assert mock_message.correlation_id == mock_message.id

    @pytest.mark.parametrize(
        "version",
        ["1.2.3-01", "1.2.3-alpha..1", "\u0661.\u0662.\u0663"],
    )
    def test_invalid_layout_semver_raises(self, version: str) -> None:
        """Invalid SemVer is rejected before writing a render request."""
        from notification_service.services.messaging.repository import _validate_external_layout_snapshot

        mock_message = MagicMock(spec=Message)
        mock_message.external_layout_version = version
        mock_message.external_layout_content = "<html>valid content</html>"

        with pytest.raises(NohikiError) as exc_info:
            _validate_external_layout_snapshot(mock_message)

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR

    @pytest.mark.asyncio
    async def test_enqueue_preserves_bool_in_struct(self) -> None:
        """Bool values are preserved in Struct, not stringified (regression)."""
        from notification_service.services.messaging.repository import _enqueue_render_request

        mock_db = create_mock_session()
        mock_message = MagicMock(spec=Message)
        mock_message.id = uuid4()
        mock_message.external_layout_id = uuid4()
        mock_message.external_layout_version = "1.2.3"
        mock_message.external_layout_content = "<html>{{ flag }}</html>"
        mock_message.correlation_id = None
        writer = MagicMock()
        writer.write_event = AsyncMock()

        with patch(
            "notification_service.services.messaging.repository.OutboxWriter",
            return_value=writer,
        ):
            await _enqueue_render_request(mock_db, mock_message, {"flag": True})

        write_call = writer.write_event.await_args
        assert write_call is not None
        event = write_call.kwargs["event"]
        assert event.template_version == "1.2.3"
        assert event.template_content == "<html>{{ flag }}</html>"
        assert event.data.to_dict()["flag"] is True


class TestMessageRepositoryCreate:
    """Tests for MessageRepository.create method."""

    @pytest.fixture
    def repository(self) -> MessageRepository:
        """Provide a MessageRepository instance."""
        return MessageRepository()

    @pytest.fixture
    def valid_message_create(self) -> MessageCreate:
        """Provide valid message creation data."""
        return MessageCreate(
            user_id=uuid4(),
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            subject="Test Subject",
            body="Test body content",
        )

    @pytest.mark.asyncio
    async def test_create_success(self, repository: MessageRepository, valid_message_create: MessageCreate) -> None:
        """Successful message creation returns Message entity."""
        mock_db = create_mock_session()
        mock_db.add = MagicMock()

        with patch(
            "notification_service.services.messaging.repository.is_channel_supported",
            return_value=True,
        ):
            result = await repository.create(mock_db, valid_message_create)

        assert result is not None
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_create_unsupported_channel_raises(self, repository: MessageRepository) -> None:
        """Unsupported channel raises validation error."""
        mock_db = create_mock_session()
        message = MessageCreate(
            user_id=uuid4(),
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            subject="Test",
            body="Body",
        )

        with (
            patch(
                "notification_service.services.messaging.repository.is_channel_supported",
                return_value=False,
            ),
            pytest.raises(NohikiError) as exc_info,
        ):
            await repository.create(mock_db, message)

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR
        assert "not supported" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_create_integrity_error_rollback(
        self,
        repository: MessageRepository,
        valid_message_create: MessageCreate,
    ) -> None:
        """IntegrityError during create triggers rollback."""
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.commit.side_effect = IntegrityError(None, None, Exception("Duplicate"))

        with (
            patch(
                "notification_service.services.messaging.repository.is_channel_supported",
                return_value=True,
            ),
            pytest.raises(NohikiError) as exc_info,
        ):
            await repository.create(mock_db, valid_message_create)

        assert exc_info.value.error_code == ErrorCode.DATABASE_ERROR
        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_listing_returns_existing_message(self, repository: MessageRepository) -> None:
        """Re-enqueueing the same user/listing resolves to the persisted message."""
        user_id = uuid4()
        listing_id = uuid4()
        message = MessageCreate(
            user_id=user_id,
            stored_listing_id=listing_id,
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            subject="Test",
            body="Body",
        )
        existing = MagicMock(spec=Message)
        existing.id = uuid4()
        mock_db = create_mock_session()
        mock_db.commit.side_effect = IntegrityError(None, None, Exception("Duplicate"))
        mock_db.scalar.return_value = existing

        with patch(
            "notification_service.services.messaging.repository.is_channel_supported",
            return_value=True,
        ):
            result = await repository.create(mock_db, message)

        assert result is existing
        mock_db.rollback.assert_awaited_once()


class TestMessageRepositoryGetById:
    """Tests for MessageRepository.get_by_id method."""

    @pytest.fixture
    def repository(self) -> MessageRepository:
        """Provide a MessageRepository instance."""
        return MessageRepository()

    @pytest.mark.asyncio
    async def test_get_by_id_success(self, repository: MessageRepository) -> None:
        """Successful retrieval returns Message entity."""
        mock_db = create_mock_session()
        message_id = uuid4()
        mock_message = MagicMock(spec=Message)
        mock_message.id = message_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_db.execute.return_value = mock_result

        result = await repository.get_by_id(mock_db, message_id)

        assert result.id == message_id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found_raises(self, repository: MessageRepository) -> None:
        """Message not found raises NOT_FOUND error."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(NohikiError) as exc_info:
            await repository.get_by_id(mock_db, uuid4())

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_by_id_database_error(self, repository: MessageRepository) -> None:
        """Database error during retrieval raises DATABASE_ERROR."""
        mock_db = create_mock_session()
        mock_db.execute.side_effect = Exception("Connection failed")

        with pytest.raises(NohikiError) as exc_info:
            await repository.get_by_id(mock_db, uuid4())

        assert exc_info.value.error_code == ErrorCode.DATABASE_ERROR


class TestMessageRepositoryGetList:
    """Tests for MessageRepository.get_list method."""

    @pytest.fixture
    def repository(self) -> MessageRepository:
        """Provide a MessageRepository instance."""
        return MessageRepository()

    @pytest.mark.asyncio
    async def test_get_list_with_filters(self, repository: MessageRepository) -> None:
        """get_list applies filters and returns paginated results."""
        mock_db = create_mock_session()
        mock_messages = [MagicMock(spec=Message)]

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = mock_messages

        mock_db.execute.side_effect = [mock_count_result, mock_list_result]

        params = MessageQueryParams(
            db=mock_db,
            user_id=uuid4(),
            status=MessageStatus.PENDING.value,
            page=1,
            size=10,
        )

        result = await repository.get_list(params)

        assert result.total == 1
        assert len(result.messages) == 1
        assert result.page == 1
        assert result.size == 10


class TestMessageRepositoryUpdate:
    """Tests for MessageRepository.update method."""

    @pytest.fixture
    def repository(self) -> MessageRepository:
        """Provide a MessageRepository instance."""
        return MessageRepository()

    @pytest.mark.asyncio
    async def test_update_success(self, repository: MessageRepository) -> None:
        """Successful update returns updated Message."""
        mock_db = create_mock_session()
        message_id = uuid4()
        mock_message = MagicMock(spec=Message)
        mock_message.id = message_id

        with patch.object(repository, "get_by_id", new_callable=AsyncMock, return_value=mock_message):
            result = await repository.update(mock_db, message_id, MessageUpdate(subject="Updated"))

        assert result == mock_message
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_no_changes(self, repository: MessageRepository) -> None:
        """Update with no changes still returns message."""
        mock_db = create_mock_session()
        message_id = uuid4()
        mock_message = MagicMock(spec=Message)

        with patch.object(repository, "get_by_id", new_callable=AsyncMock, return_value=mock_message):
            result = await repository.update(mock_db, message_id, MessageUpdate())

        assert result == mock_message


class TestMessageRepositoryCancel:
    """Tests for MessageRepository.cancel method."""

    @pytest.fixture
    def repository(self) -> MessageRepository:
        """Provide a MessageRepository instance."""
        return MessageRepository()

    @pytest.mark.asyncio
    async def test_cancel_pending_message(self, repository: MessageRepository) -> None:
        """Cancelling pending message sets status to CANCELLED."""
        mock_db = create_mock_session()
        message_id = uuid4()
        mock_message = MagicMock(spec=Message)
        mock_message.status = MessageStatus.PENDING

        with patch.object(repository, "get_by_id", new_callable=AsyncMock, return_value=mock_message):
            result = await repository.cancel(mock_db, message_id)

        assert result.status == MessageStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_sent_message_raises(self, repository: MessageRepository) -> None:
        """Cancelling already-sent message raises validation error."""
        mock_db = create_mock_session()
        mock_message = MagicMock(spec=Message)
        mock_message.status = MessageStatus.SENT

        with (
            patch.object(repository, "get_by_id", new_callable=AsyncMock, return_value=mock_message),
            pytest.raises(NohikiError) as exc_info,
        ):
            await repository.cancel(mock_db, uuid4())

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR

    @pytest.mark.asyncio
    async def test_cancel_failed_message_raises(self, repository: MessageRepository) -> None:
        """Cancelling failed message raises validation error."""
        mock_db = create_mock_session()
        mock_message = MagicMock(spec=Message)
        mock_message.status = MessageStatus.FAILED

        with (
            patch.object(repository, "get_by_id", new_callable=AsyncMock, return_value=mock_message),
            pytest.raises(NohikiError) as exc_info,
        ):
            await repository.cancel(mock_db, uuid4())

        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR


class TestMessageRepositoryGetStats:
    """Tests for MessageRepository.get_stats method."""

    @pytest.fixture
    def repository(self) -> MessageRepository:
        """Provide a MessageRepository instance."""
        return MessageRepository()

    @pytest.mark.asyncio
    async def test_get_stats_success(self, repository: MessageRepository) -> None:
        """get_stats returns aggregated counts by status."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (MessageStatus.PENDING, 10),
            (MessageStatus.SENT, 5),
            (MessageStatus.FAILED, 3),
        ]
        mock_db.execute.return_value = mock_result

        result = await repository.get_stats(mock_db)

        assert result.total == 18
        assert result.by_status[MessageStatus.PENDING.value] == 10
        assert result.by_status[MessageStatus.SENT.value] == 5
        assert result.by_status[MessageStatus.FAILED.value] == 3

    @pytest.mark.asyncio
    async def test_get_stats_database_error(self, repository: MessageRepository) -> None:
        """Database error during stats query raises DATABASE_ERROR."""
        mock_db = create_mock_session()
        mock_db.execute.side_effect = Exception("Query failed")

        with pytest.raises(NohikiError) as exc_info:
            await repository.get_stats(mock_db)

        assert exc_info.value.error_code == ErrorCode.DATABASE_ERROR

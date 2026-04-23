"""Tests for NotificationService orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_fastapi_utils.errors import ErrorCode, NohikiError
from notification_service.db.models import Message
from notification_service.services.messaging import (
    BatchJobNotificationParams,
    NotificationService,
)
from notification_service.services.messaging.repository import MessageRepository


class TestNotificationServiceInit:
    """Tests for NotificationService initialization."""

    def test_init_creates_default_repository(self) -> None:
        """Service creates default repository if none provided."""
        service = NotificationService()
        assert service._repository is not None
        assert isinstance(service._repository, MessageRepository)

    def test_init_accepts_custom_repository(self) -> None:
        """Service accepts injected repository."""
        custom_repo = MagicMock(spec=MessageRepository)
        service = NotificationService(repository=custom_repo)
        assert service._repository is custom_repo


class TestSendJobNotificationEcst:
    """Tests for send_job_notification_ecst method."""

    @pytest.fixture
    def mock_repo(self) -> AsyncMock:
        """Provide mock repository."""
        repo = AsyncMock()
        mock_message = MagicMock(spec=Message)
        mock_message.id = uuid4()
        repo.create.return_value = mock_message
        return repo

    @pytest.fixture
    def service(self, mock_repo: AsyncMock) -> NotificationService:
        """Provide NotificationService with mocked repository."""
        return NotificationService(repository=mock_repo)

    @pytest.fixture
    def valid_params(self) -> BatchJobNotificationParams:
        """Provide valid batch notification parameters."""
        return BatchJobNotificationParams(
            user_id=uuid4(),
            role_id=uuid4(),
            listing_id=uuid4(),
            subject="Test Job Match",
            stored_listing_ids=[uuid4()],
            channels=["email"],
            listings=[{"title": "Software Engineer", "company": "Acme Corp"}],
        )

    @pytest.mark.asyncio
    async def test_send_ecst_success(
        self,
        service: NotificationService,
        mock_repo: AsyncMock,
        valid_params: BatchJobNotificationParams,
    ) -> None:
        """Successful ECST notification returns created messages."""
        mock_db = create_mock_session()

        result = await service.send_job_notification_ecst(
            params=valid_params,
            recipient_email="user@example.com",
            db=mock_db,
        )

        assert len(result) == 1
        mock_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_ecst_no_channels_raises(self, service: NotificationService) -> None:
        """Empty channels list raises validation error."""
        mock_db = create_mock_session()
        params = BatchJobNotificationParams(
            user_id=uuid4(),
            role_id=uuid4(),
            listing_id=uuid4(),
            subject="Test",
            stored_listing_ids=[],
            channels=[],
        )

        with pytest.raises(NohikiError) as exc_info:
            await service.send_job_notification_ecst(params, "user@example.com", mock_db)

        assert exc_info.value.error_code == ErrorCode.INVALID_REQUEST
        assert "No notification channels" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_send_ecst_invalid_channels_raises(self, service: NotificationService) -> None:
        """Invalid channel names raise validation error."""
        mock_db = create_mock_session()
        params = BatchJobNotificationParams(
            user_id=uuid4(),
            role_id=uuid4(),
            listing_id=uuid4(),
            subject="Test",
            stored_listing_ids=[],
            channels=["invalid_channel"],
        )

        with pytest.raises(NohikiError) as exc_info:
            await service.send_job_notification_ecst(params, "user@example.com", mock_db)

        assert exc_info.value.error_code == ErrorCode.INVALID_REQUEST
        assert "Invalid notification channels" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_send_ecst_multiple_channels(self, service: NotificationService, mock_repo: AsyncMock) -> None:
        """Multiple valid channels create multiple messages."""
        mock_db = create_mock_session()
        params = BatchJobNotificationParams(
            user_id=uuid4(),
            role_id=uuid4(),
            listing_id=uuid4(),
            subject="Test",
            stored_listing_ids=[],
            channels=["email", "email"],
        )

        result = await service.send_job_notification_ecst(
            params=params,
            recipient_email="user@example.com",
            db=mock_db,
        )

        assert len(result) == 2
        assert mock_repo.create.call_count == 2


class TestEnqueueJobNotificationMessages:
    """Tests for enqueue_job_notification_messages method."""

    @pytest.fixture
    def mock_repo(self) -> AsyncMock:
        """Provide mock repository."""
        repo = AsyncMock()
        mock_message = MagicMock(spec=Message)
        mock_message.id = uuid4()
        repo.create.return_value = mock_message
        return repo

    @pytest.fixture
    def service(self, mock_repo: AsyncMock) -> NotificationService:
        """Provide NotificationService with mocked repository."""
        return NotificationService(repository=mock_repo)

    @pytest.mark.asyncio
    async def test_enqueue_success(self, service: NotificationService) -> None:
        """Successful enqueue returns created messages."""
        mock_db = create_mock_session()
        from notification_service.services.messaging.models import NotificationParams

        params = NotificationParams(
            user_id=uuid4(),
            channels=["email"],
            recipient_email="test@example.com",
            template_vars={"job_title": "Engineer"},
        )

        with patch(
            "notification_service.services.messaging.notification_service.is_channel_supported",
            return_value=True,
        ):
            result = await service.enqueue_job_notification_messages(mock_db, params)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_enqueue_skips_unsupported_channel(self, service: NotificationService) -> None:
        """Unsupported channels are skipped without error."""
        mock_db = create_mock_session()
        from notification_service.services.messaging.models import NotificationParams

        params = NotificationParams(
            user_id=uuid4(),
            channels=["email"],
            recipient_email="test@example.com",
            template_vars={},
        )

        with patch(
            "notification_service.services.messaging.notification_service.is_channel_supported",
            return_value=False,
        ):
            result = await service.enqueue_job_notification_messages(mock_db, params)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_enqueue_skips_no_recipient(self, service: NotificationService) -> None:
        """Missing recipient skips channel without error."""
        mock_db = create_mock_session()
        from notification_service.services.messaging.models import NotificationParams

        params = NotificationParams(
            user_id=uuid4(),
            channels=["email"],
            recipient_email=None,
            template_vars={},
        )

        with patch(
            "notification_service.services.messaging.notification_service.is_channel_supported",
            return_value=True,
        ):
            result = await service.enqueue_job_notification_messages(mock_db, params)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_enqueue_handles_creation_error(self, service: NotificationService, mock_repo: AsyncMock) -> None:
        """Repository error during creation is handled gracefully."""
        mock_db = create_mock_session()
        mock_repo.create.side_effect = Exception("Creation failed")
        from notification_service.services.messaging.models import NotificationParams

        params = NotificationParams(
            user_id=uuid4(),
            channels=["email"],
            recipient_email="test@example.com",
            template_vars={},
        )

        with patch(
            "notification_service.services.messaging.notification_service.is_channel_supported",
            return_value=True,
        ):
            result = await service.enqueue_job_notification_messages(mock_db, params)

        assert len(result) == 0

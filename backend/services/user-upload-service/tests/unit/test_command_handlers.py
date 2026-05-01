"""Unit tests for upload command handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from user_upload_service.events.handlers import (
    handle_upload_create_requested,
    handle_upload_delete_requested,
)


def _make_context(
    *,
    db_session: MagicMock | AsyncMock | None = None,
    outbox: MagicMock | None = None,
) -> MessageContext:
    """Build a ``MessageContext`` with injected db_session/outbox."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
        outbox=outbox,
    )


class TestHandleUploadCreateRequested:
    """Tests for handle_upload_create_requested handler."""

    @pytest.fixture
    def mock_message(self) -> MagicMock:
        """Create mock UploadCreateRequested message."""
        msg = MagicMock()
        msg.request_id = str(uuid4())
        msg.user_id = str(uuid4())
        msg.storage_key = f"uploads/{uuid4()}/test.pdf"
        msg.filename = "test.pdf"
        msg.content_type = "application/pdf"
        msg.file_size = 1024
        msg.content_hash = "abc123def456"
        return msg

    @pytest.mark.asyncio
    async def test_creates_upload_metadata_successfully(
        self,
        mock_message: MagicMock,
    ) -> None:
        """Handler creates upload metadata and publishes event."""
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch("user_upload_service.events.handlers.attachment_service") as mock_service,
            patch(
                "user_upload_service.events.handlers.publish_attachment_created_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_service.exists_by_id = AsyncMock(return_value=False)
            mock_attachment = MagicMock()
            mock_attachment.id = uuid4()
            mock_service.create_metadata = AsyncMock(return_value=mock_attachment)

            await handle_upload_create_requested(mock_message, context)

            mock_service.create_metadata.assert_called_once()
            mock_publish.assert_awaited_once_with(mock_db, mock_outbox, mock_attachment)

    @pytest.mark.asyncio
    async def test_skips_duplicate_upload(
        self,
        mock_message: MagicMock,
    ) -> None:
        """Handler skips processing if upload already exists."""
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with patch("user_upload_service.events.handlers.attachment_service") as mock_service:
            mock_service.exists_by_id = AsyncMock(return_value=True)

            await handle_upload_create_requested(mock_message, context)

            mock_service.create_metadata.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_request_id_as_upload_id(
        self,
        mock_message: MagicMock,
    ) -> None:
        """Handler uses request_id as the upload_id for idempotency."""
        request_id = str(uuid4())
        mock_message.request_id = request_id
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch("user_upload_service.events.handlers.attachment_service") as mock_service,
            patch(
                "user_upload_service.events.handlers.publish_attachment_created_event",
                new_callable=AsyncMock,
            ),
            patch("user_upload_service.events.handlers.UploadMetadataInput") as mock_input_cls,
        ):
            mock_service.exists_by_id = AsyncMock(return_value=False)
            mock_attachment = MagicMock()
            mock_service.create_metadata = AsyncMock(return_value=mock_attachment)

            await handle_upload_create_requested(mock_message, context)

            call_kwargs = mock_input_cls.call_args.kwargs
            assert str(call_kwargs["upload_id"]) == request_id


class TestHandleUploadDeleteRequested:
    """Tests for handle_upload_delete_requested handler."""

    @pytest.fixture
    def mock_message(self) -> MagicMock:
        """Create mock UploadDeleteRequested message."""
        msg = MagicMock()
        msg.request_id = str(uuid4())
        msg.user_id = str(uuid4())
        msg.upload_id = str(uuid4())
        return msg

    @pytest.mark.asyncio
    async def test_deletes_upload_successfully(
        self,
        mock_message: MagicMock,
    ) -> None:
        """Handler deletes upload and publishes event."""
        user_id = uuid4()
        mock_message.user_id = str(user_id)
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch("user_upload_service.events.handlers.attachment_service") as mock_service,
            patch(
                "user_upload_service.events.handlers.publish_attachment_deleted_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_attachment = MagicMock()
            mock_attachment.user_id = user_id
            mock_service.get_attachment_by_id_or_none = AsyncMock(return_value=mock_attachment)
            mock_service.delete_attachment = AsyncMock()

            await handle_upload_delete_requested(mock_message, context)

            mock_service.delete_attachment.assert_called_once()
            mock_publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_if_upload_not_found(
        self,
        mock_message: MagicMock,
    ) -> None:
        """Handler skips if upload doesn't exist (idempotent delete)."""
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with patch("user_upload_service.events.handlers.attachment_service") as mock_service:
            mock_service.get_attachment_by_id_or_none = AsyncMock(return_value=None)

            await handle_upload_delete_requested(mock_message, context)

            mock_service.delete_attachment.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_if_user_does_not_own_upload(
        self,
        mock_message: MagicMock,
    ) -> None:
        """Handler skips if user doesn't own the upload."""
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with patch("user_upload_service.events.handlers.attachment_service") as mock_service:
            mock_attachment = MagicMock()
            mock_attachment.user_id = uuid4()  # Different user
            mock_service.get_attachment_by_id_or_none = AsyncMock(return_value=mock_attachment)

            await handle_upload_delete_requested(mock_message, context)

            mock_service.delete_attachment.assert_not_called()

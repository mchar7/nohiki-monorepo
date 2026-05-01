"""Unit tests for handle_user_deleted event handler."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.user.auth.v1 import AccountDeleted
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from user_upload_service.events.handlers import handle_user_deleted


def _make_context(
    *,
    db_session: MagicMock | AsyncMock | None = None,
    outbox: MagicMock | None = None,
) -> MessageContext:
    """Build a ``MessageContext`` with injected db_session and outbox."""
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


class TestHandleUserDeleted:
    """Tests for handle_user_deleted handler."""

    @pytest.mark.asyncio
    async def test_deletes_user_attachments_and_publishes_events(self) -> None:
        """Deletes all attachments for deleted user and publishes UploadDeleted for each."""
        user_id = uuid.uuid4()
        message = AccountDeleted(user_id=str(user_id))
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        mock_s3_client = MagicMock()

        att1 = MagicMock()
        att1.id = uuid.uuid4()
        att1.user_id = user_id
        att2 = MagicMock()
        att2.id = uuid.uuid4()
        att2.user_id = user_id

        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch("user_upload_service.events.handlers._s3_client", mock_s3_client),
            patch(
                "user_upload_service.events.handlers.attachment_service.delete_user_attachments",
                new_callable=AsyncMock,
                return_value=[att1, att2],
            ) as mock_delete,
            patch(
                "user_upload_service.events.handlers.publish_attachment_deleted_batch",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            await handle_user_deleted(message, context)

            mock_delete.assert_awaited_once_with(mock_db, mock_s3_client, user_id)
            mock_publish.assert_awaited_once_with(mock_db, mock_outbox, [att1, att2])

    @pytest.mark.asyncio
    async def test_rejects_empty_user_id(self) -> None:
        """Rejects a destructive event when user_id is empty."""
        message = AccountDeleted(user_id="")
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())

        with pytest.raises(ValueError, match="user_id"):
            await handle_user_deleted(message, context)

"""Unit tests for event handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from user_entitlement_service.events.handlers import (
    _handle_account_updated,
    _handle_user_deleted,
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


class TestHandleAccountUpdated:
    """Tests for _handle_account_updated event handler."""

    @pytest.mark.asyncio
    async def test_creates_default_entitlements_for_new_user(self) -> None:
        """Handler delegates to create_default_entitlements and publishes via outbox."""
        user_id = uuid4()
        mock_db = create_mock_session()
        mock_db.begin_nested = MagicMock(return_value=AsyncMock())
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_entitlements = MagicMock()
        mock_entitlements.id = uuid4()
        mock_entitlements.tier = "FREE"

        with (
            patch(
                "user_entitlement_service.events.handlers.create_default_entitlements",
                new_callable=AsyncMock,
                return_value=mock_entitlements,
            ) as mock_create,
            patch(
                "user_entitlement_service.events.handlers.publish_entitlements_changed_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            from nohiki.user.auth.v1 import AccountUpdated

            message = AccountUpdated(user_id=str(user_id))
            await _handle_account_updated(message, context)

            mock_create.assert_awaited_once_with(mock_db, user_id)
            mock_publish.assert_awaited_once_with(mock_db, mock_outbox, mock_entitlements)

    @pytest.mark.asyncio
    async def test_propagates_exception_on_create_failure(self) -> None:
        """Exceptions from create_default_entitlements propagate to the caller."""
        user_id = uuid4()
        mock_db = create_mock_session()
        mock_db.begin_nested = MagicMock(return_value=AsyncMock())
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with patch(
            "user_entitlement_service.events.handlers.create_default_entitlements",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Duplicate"),
        ):
            from nohiki.user.auth.v1 import AccountUpdated

            message = AccountUpdated(user_id=str(user_id))
            with pytest.raises(RuntimeError, match="Duplicate"):
                await _handle_account_updated(message, context)

    @pytest.mark.asyncio
    async def test_raises_on_missing_user_id(self) -> None:
        """Handler raises ValueError when user_id is empty."""
        from nohiki.user.auth.v1 import AccountUpdated

        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = AccountUpdated(user_id="")

        with pytest.raises(ValueError, match="user_id is required"):
            await _handle_account_updated(message, context)


class TestHandleUserDeleted:
    """Tests for _handle_user_deleted event handler."""

    @pytest.mark.asyncio
    async def test_deletes_entitlements_for_user(self) -> None:
        """Handler delegates to delete_entitlements with the injected session."""
        user_id = uuid4()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch(
            "user_entitlement_service.events.handlers.delete_entitlements",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_delete:
            from nohiki.user.auth.v1 import AccountDeleted

            message = AccountDeleted(user_id=str(user_id))
            await _handle_user_deleted(message, context)

            mock_delete.assert_awaited_once_with(mock_db, user_id)

    @pytest.mark.asyncio
    async def test_propagates_exception_on_delete_failure(self) -> None:
        """Exceptions from delete_entitlements propagate to the caller."""
        user_id = uuid4()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch(
            "user_entitlement_service.events.handlers.delete_entitlements",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Not found"),
        ):
            from nohiki.user.auth.v1 import AccountDeleted

            message = AccountDeleted(user_id=str(user_id))
            with pytest.raises(RuntimeError, match="Not found"):
                await _handle_user_deleted(message, context)

    @pytest.mark.asyncio
    async def test_rejects_missing_user_id(self) -> None:
        """Handler rejects an unprocessable deletion event without touching the DB."""
        from nohiki.user.auth.v1 import AccountDeleted

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)
        message = AccountDeleted(user_id="")

        with patch(
            "user_entitlement_service.events.handlers.delete_entitlements",
            new_callable=AsyncMock,
        ) as mock_delete:
            with pytest.raises(ValueError, match="user_id is required"):
                await _handle_user_deleted(message, context)
            mock_delete.assert_not_awaited()

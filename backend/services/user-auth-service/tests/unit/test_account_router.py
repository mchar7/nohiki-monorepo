"""Unit tests for user_auth_service.api.routers.account module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Response
from nohiki_db_utils.testing import create_mock_session
from user_auth_service.api.routers.account import (
    delete_account,
    get_account,
    get_current_active_user_id,
    get_oauth_identities,
    get_outbox,
    unlink_oauth_provider,
    update_account,
)
from user_auth_service.api.schemas import UpdateUserRequest, UserResponse
from user_auth_service.api.schemas.oauth import OAuthIdentitiesResponse, OAuthProvider
from user_auth_service.db.models import Account, OAuthIdentity
from user_auth_service.services.oauth_service import OAuthError


class TestGetOutbox:
    """Tests for get_outbox dependency."""

    @pytest.mark.asyncio
    async def test_returns_outbox_writer(self) -> None:
        """Returns an OutboxWriter instance from async generator."""
        from nohiki_db_utils import OutboxWriter

        async_gen = get_outbox()
        result = await anext(async_gen)
        assert isinstance(result, OutboxWriter)


class TestGetCurrentActiveUserId:
    """Tests for rejecting stale tokens after account deactivation."""

    @pytest.mark.asyncio
    async def test_returns_active_account_id(self) -> None:
        """An access token remains usable while its account is active."""
        user_id = uuid.uuid4()
        account = MagicMock(spec=Account)
        account.is_active = True
        mock_db = create_mock_session()
        mock_db.get = AsyncMock(return_value=account)

        assert await get_current_active_user_id(user_id, mock_db) == user_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("account", [None, MagicMock(spec=Account, is_active=False)])
    async def test_rejects_missing_or_inactive_account(self, account: Account | None) -> None:
        """A validly signed token cannot authenticate a deleted or inactive account."""
        mock_db = create_mock_session()
        mock_db.get = AsyncMock(return_value=account)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user_id(uuid.uuid4(), mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Account is inactive"


class TestGetAccount:
    """Tests for get_account endpoint."""

    @pytest.mark.asyncio
    async def test_returns_user_account(self) -> None:
        """Returns user account information."""
        user_id = uuid.uuid4()
        now = datetime.now(UTC)

        mock_db = create_mock_session()

        mock_user = MagicMock(spec=Account)
        mock_user.id = user_id
        mock_user.email = "user@example.com"
        mock_user.first_name = "Test"
        mock_user.last_name = "Account"
        mock_user.display_name = "Test Account"
        mock_user.is_active = True
        mock_user.created_at = now
        mock_user.updated_at = now

        with patch(
            "user_auth_service.api.routers.account.user_service.get_user_by_id",
            new_callable=AsyncMock,
            return_value=mock_user,
        ):
            result = await get_account(mock_db, user_id)

        assert isinstance(result, UserResponse)
        assert result.id == user_id
        assert result.email == "user@example.com"


class TestUpdateAccount:
    """Tests for update_account endpoint."""

    @pytest.mark.asyncio
    async def test_updates_account_successfully(self) -> None:
        """Updates user account and returns response."""
        user_id = uuid.uuid4()
        now = datetime.now(UTC)

        update_data = UpdateUserRequest(
            first_name="Updated",
            last_name="Name",
        )

        mock_db = create_mock_session()
        mock_db.commit = AsyncMock()
        mock_outbox = MagicMock()

        mock_user = MagicMock(spec=Account)
        mock_user.id = user_id
        mock_user.email = "user@example.com"
        mock_user.first_name = "Updated"
        mock_user.last_name = "Name"
        mock_user.display_name = "Updated Name"
        mock_user.is_active = True
        mock_user.created_at = now
        mock_user.updated_at = now

        with (
            patch(
                "user_auth_service.api.routers.account.user_service.update_user",
                new_callable=AsyncMock,
                return_value=mock_user,
            ),
            patch(
                "user_auth_service.api.routers.account.publish_user_updated_event",
                new_callable=AsyncMock,
            ),
        ):
            result = await update_account(update_data, mock_db, user_id, mock_outbox)

        assert result.first_name == "Updated"
        assert result.last_name == "Name"
        mock_db.commit.assert_awaited_once()


class TestDeleteAccount:
    """Tests for delete_account endpoint."""

    @pytest.mark.asyncio
    async def test_deletes_account_successfully(self) -> None:
        """Deletes user account and clears auth cookies."""
        user_id = uuid.uuid4()
        order: list[str] = []

        mock_response = MagicMock(spec=Response)
        mock_db = create_mock_session()
        mock_db.commit = AsyncMock(side_effect=lambda: order.append("commit"))
        mock_outbox = MagicMock()

        with (
            patch(
                "user_auth_service.api.routers.account.user_service.delete_user",
                new=AsyncMock(side_effect=lambda *_args, **_kwargs: order.append("delete")),
            ),
            patch(
                "user_auth_service.api.routers.account.publish_user_deleted_event",
                new=AsyncMock(side_effect=lambda *_args, **_kwargs: order.append("outbox")),
            ),
            patch(
                "user_auth_service.api.routers.account.clear_auth_cookies",
            ) as mock_clear,
            patch(
                "user_auth_service.api.routers.account.get_token_blacklist",
            ) as mock_get_blacklist,
        ):
            mock_blacklist = MagicMock()
            mock_blacklist.revoke_all_for_user = AsyncMock(side_effect=lambda *_args, **_kwargs: order.append("redis"))
            mock_get_blacklist.return_value = mock_blacklist

            result = await delete_account(mock_response, mock_db, user_id, mock_outbox)

        # Returns None (204 No Content)
        assert result is None
        mock_db.commit.assert_awaited_once()
        mock_clear.assert_called_once()
        assert mock_clear.call_args[0][0] is mock_response
        mock_blacklist.revoke_all_for_user.assert_awaited_once()
        assert order == ["delete", "outbox", "commit", "redis"]


class TestGetOAuthIdentities:
    """Tests for get_oauth_identities endpoint."""

    @pytest.mark.asyncio
    async def test_returns_linked_identities(self) -> None:
        """Returns list of linked OAuth identities."""
        account_id = uuid.uuid4()
        now = datetime.now(UTC)

        mock_db = create_mock_session()
        mock_account = MagicMock(spec=Account)
        mock_account.has_password = True
        mock_db.get = AsyncMock(return_value=mock_account)

        mock_identity = MagicMock(spec=OAuthIdentity)
        mock_identity.provider = "github"
        mock_identity.provider_username = "testuser"
        mock_identity.provider_email = "test@github.com"
        mock_identity.created_at = now

        mock_oauth_service = MagicMock()
        mock_oauth_service.get_linked_identities = AsyncMock(return_value=[mock_identity])

        result = await get_oauth_identities(account_id, mock_db, mock_oauth_service)

        assert isinstance(result, OAuthIdentitiesResponse)
        assert len(result.identities) == 1
        assert result.identities[0].provider == OAuthProvider.GITHUB
        assert result.identities[0].provider_username == "testuser"
        assert result.has_password is True

    @pytest.mark.asyncio
    async def test_raises_404_when_account_not_found(self) -> None:
        """Raises HTTPException when account not found."""
        account_id = uuid.uuid4()

        mock_db = create_mock_session()
        mock_db.get = AsyncMock(return_value=None)

        mock_oauth_service = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_identities(account_id, mock_db, mock_oauth_service)

        assert exc_info.value.status_code == 404


class TestUnlinkOAuthProvider:
    """Tests for unlink_oauth_provider endpoint."""

    @pytest.mark.asyncio
    async def test_unlinks_identity_successfully(self) -> None:
        """Unlinks OAuth identity and commits."""
        account_id = uuid.uuid4()

        mock_db = create_mock_session()
        mock_db.commit = AsyncMock()

        mock_oauth_service = MagicMock()
        mock_oauth_service.unlink_identity = AsyncMock(return_value=True)

        result = await unlink_oauth_provider(
            OAuthProvider.GITHUB,
            account_id,
            mock_db,
            mock_oauth_service,
        )

        assert result is None
        mock_oauth_service.unlink_identity.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_404_when_identity_not_found(self) -> None:
        """Raises HTTPException when identity not found."""
        account_id = uuid.uuid4()

        mock_db = create_mock_session()
        mock_oauth_service = MagicMock()
        mock_oauth_service.unlink_identity = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await unlink_oauth_provider(
                OAuthProvider.GITHUB,
                account_id,
                mock_db,
                mock_oauth_service,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_400_on_oauth_error(self) -> None:
        """Raises HTTPException on OAuthError."""
        account_id = uuid.uuid4()

        mock_db = create_mock_session()
        mock_oauth_service = MagicMock()
        mock_oauth_service.unlink_identity = AsyncMock(
            side_effect=OAuthError("cannot_unlink", "Cannot unlink only auth method")
        )

        with pytest.raises(HTTPException) as exc_info:
            await unlink_oauth_provider(
                OAuthProvider.GITHUB,
                account_id,
                mock_db,
                mock_oauth_service,
            )

        assert exc_info.value.status_code == 400
        assert "Cannot unlink" in exc_info.value.detail

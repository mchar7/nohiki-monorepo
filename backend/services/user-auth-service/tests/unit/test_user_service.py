"""Unit tests for identity_service.services.user_service module."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_fastapi_utils.errors import ConflictError, NotFoundError
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from user_auth_service.api.schemas import CreateUserRequest
from user_auth_service.db.models import Account
from user_auth_service.services.user_service import (
    authenticate_user,
    create_user,
    delete_user,
    get_user_by_email,
    get_user_by_id,
    update_user,
)


class TestCreateUser:
    """Tests for create_user function."""

    @pytest.mark.asyncio
    async def test_creates_user_successfully(self) -> None:
        """Creates user with all provided fields."""
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        # No existing user with email
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        user_create = CreateUserRequest(
            email="newuser@example.com",
            password=SecretStr("SecurePassword123!"),
            display_name="\u00a0李\u2003小龍\u3000",
        )

        user = await create_user(mock_db, user_create)

        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()
        assert user.email == "newuser@example.com"
        assert user.display_name == "李 小龍"
        assert user.first_name is None
        assert user.last_name is None

    @pytest.mark.asyncio
    async def test_raises_conflict_for_existing_email(self) -> None:
        """Raises ConflictError when email already exists."""
        mock_db = create_mock_session()

        # Existing user with email
        existing_user = MagicMock(spec=Account)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        user_create = MagicMock()
        user_create.email = "existing@example.com"
        user_create.password = SecretStr("Password123!")

        with pytest.raises(ConflictError, match="Email already exists"):
            await create_user(mock_db, user_create)

    @pytest.mark.asyncio
    async def test_maps_concurrent_email_insert_conflict(self) -> None:
        """A uniqueness race after the pre-check surfaces the public conflict error."""
        mock_db = create_mock_session()
        no_existing_user = MagicMock()
        no_existing_user.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=no_existing_user)
        mock_db.flush = AsyncMock(
            side_effect=IntegrityError("INSERT INTO accounts", {}, RuntimeError("duplicate email"))
        )

        user_create = MagicMock()
        user_create.email = "raced@example.com"
        user_create.password = SecretStr("Password123!")
        user_create.display_name = "Race User"

        with pytest.raises(ConflictError, match="Email already exists"):
            await create_user(mock_db, user_create)

    @pytest.mark.asyncio
    async def test_hashes_password(self) -> None:
        """Hashes password before storing."""
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        user_create = MagicMock()
        user_create.email = "test@example.com"
        user_create.password = SecretStr("PlainPassword123!")
        user_create.display_name = "Test User"

        user = await create_user(mock_db, user_create)

        # Password should be hashed (argon2 format)
        assert user.hashed_password is not None
        assert user.hashed_password.startswith("$argon2")
        assert user.hashed_password != "PlainPassword123!"


class TestGetUserById:
    """Tests for get_user_by_id function."""

    @pytest.mark.asyncio
    async def test_returns_user_when_found(self) -> None:
        """Returns user when it exists."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()

        expected_user = MagicMock(spec=Account)
        expected_user.id = user_id
        mock_db.get = AsyncMock(return_value=expected_user)

        result = await get_user_by_id(mock_db, user_id)

        assert result == expected_user
        mock_db.get.assert_awaited_once_with(Account, user_id)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_missing(self) -> None:
        """Raises NotFoundError when user doesn't exist."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError, match="Account"):
            await get_user_by_id(mock_db, user_id)


class TestGetUserByEmail:
    """Tests for get_user_by_email function."""

    @pytest.mark.asyncio
    async def test_returns_user_when_found(self) -> None:
        """Returns user when email exists."""
        mock_db = create_mock_session()
        email = "test@example.com"

        expected_user = MagicMock(spec=Account)
        expected_user.email = email

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = expected_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_user_by_email(mock_db, email)

        assert result == expected_user

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        """Returns None when email doesn't exist."""
        mock_db = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_user_by_email(mock_db, "nonexistent@example.com")

        assert result is None


class TestAuthenticateUser:
    """Tests for authenticate_user function."""

    @pytest.mark.asyncio
    async def test_returns_user_on_valid_credentials(self) -> None:
        """Returns user when email and password are valid."""
        mock_db = create_mock_session()
        email = "test@example.com"
        password = "CorrectPassword123!"

        user = MagicMock(spec=Account)
        user.email = email
        user.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "user_auth_service.services.user_service.verify_password",
            return_value=True,
        ):
            result = await authenticate_user(mock_db, email, password)

        assert result == user

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_user(self) -> None:
        """Returns None when user doesn't exist."""
        mock_db = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await authenticate_user(mock_db, "nonexistent@example.com", "password")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_password(self) -> None:
        """Returns None when password is incorrect."""
        mock_db = create_mock_session()

        user = MagicMock(spec=Account)
        user.email = "test@example.com"
        user.hashed_password = "$argon2id$..."
        user.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "user_auth_service.services.user_service.verify_password",
            return_value=False,
        ):
            result = await authenticate_user(mock_db, "test@example.com", "wrong_password")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_inactive_user(self) -> None:
        """Returns None when user is inactive."""
        mock_db = create_mock_session()

        user = MagicMock(spec=Account)
        user.email = "test@example.com"
        user.hashed_password = "$argon2id$..."
        user.is_active = False
        user.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "user_auth_service.services.user_service.verify_password",
            return_value=True,
        ):
            result = await authenticate_user(mock_db, "test@example.com", "correct_password")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_oauth_only_user(self) -> None:
        """Returns None when user has no password (OAuth-only account)."""
        mock_db = create_mock_session()

        user = MagicMock(spec=Account)
        user.email = "oauth@example.com"
        user.hashed_password = None
        user.is_active = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await authenticate_user(mock_db, "oauth@example.com", "any_password")

        assert result is None


class TestUpdateUser:
    """Tests for update_user function."""

    @pytest.mark.asyncio
    async def test_updates_user_fields(self) -> None:
        """Updates user with provided fields."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        user_id = uuid.uuid4()
        existing_user = MagicMock(spec=Account)
        existing_user.id = user_id
        existing_user.first_name = "Old"
        existing_user.last_name = "Name"
        mock_db.get = AsyncMock(return_value=existing_user)

        user_update = MagicMock()
        user_update.model_dump.return_value = {
            "first_name": "New",
            "last_name": "Name",
        }

        result = await update_user(mock_db, user_id, user_update)

        assert result.first_name == "New"
        assert result.last_name == "Name"
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_password_with_hash(self) -> None:
        """Hashes new password when updating."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        user_id = uuid.uuid4()
        existing_user = MagicMock(spec=Account)
        existing_user.id = user_id
        mock_db.get = AsyncMock(return_value=existing_user)

        user_update = MagicMock()
        user_update.model_dump.return_value = {
            "password": SecretStr("NewPassword123!"),
        }

        await update_user(mock_db, user_id, user_update)

        # Password should be hashed
        assert existing_user.hashed_password.startswith("$argon2")

    @pytest.mark.asyncio
    async def test_maps_concurrent_email_update_conflict(self) -> None:
        """A raced email update surfaces conflict instead of leaking database details."""
        mock_db = create_mock_session()
        existing_user = MagicMock(spec=Account)
        existing_user.id = uuid.uuid4()
        mock_db.get = AsyncMock(return_value=existing_user)
        mock_db.flush = AsyncMock(side_effect=IntegrityError("UPDATE accounts", {}, RuntimeError("duplicate email")))
        user_update = MagicMock()
        user_update.model_dump.return_value = {"email": "taken@example.com"}

        with pytest.raises(ConflictError, match="Email already exists"):
            await update_user(mock_db, existing_user.id, user_update)

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_user(self) -> None:
        """Raises NotFoundError when user doesn't exist."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()
        mock_db.get = AsyncMock(return_value=None)

        user_update = MagicMock()

        with pytest.raises(NotFoundError):
            await update_user(mock_db, user_id, user_update)


class TestDeleteUser:
    """Tests for delete_user function."""

    @pytest.mark.asyncio
    async def test_deletes_existing_user(self) -> None:
        """Deletes user successfully."""
        mock_db = create_mock_session()
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()

        user_id = uuid.uuid4()
        existing_user = MagicMock(spec=Account)
        existing_user.id = user_id
        mock_db.get = AsyncMock(return_value=existing_user)

        await delete_user(mock_db, user_id)

        mock_db.delete.assert_awaited_once_with(existing_user)
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_user(self) -> None:
        """Raises NotFoundError when user doesn't exist."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError):
            await delete_user(mock_db, user_id)

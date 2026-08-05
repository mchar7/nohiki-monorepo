"""Unit tests for user_auth_service.events.publishers module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.testing import create_mock_session
from user_auth_service.db.models import Account
from user_auth_service.events.publishers import (
    publish_access_token_revoked_event,
    publish_user_created_event,
    publish_user_deleted_event,
    publish_user_updated_event,
)


class TestPublishUserCreatedEvent:
    """Tests for publish_user_created_event function."""

    @pytest.fixture
    def sample_user(self) -> MagicMock:
        """Create a sample user for testing."""
        user = MagicMock(spec=Account)
        user.id = uuid.uuid4()
        user.email = "test@example.com"
        user.display_name = "李 小龍"
        user.first_name = None
        user.last_name = None
        user.is_active = True
        user.created_at = datetime.now(UTC)
        user.updated_at = datetime.now(UTC)
        return user

    @pytest.mark.asyncio
    async def test_publishes_created_event(self, sample_user: Account) -> None:
        """Publishes user.created.v1 event via outbox."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event_raw = AsyncMock(return_value=uuid.uuid4())

        with patch("user_auth_service.events.publishers.kafka_client.serialize", return_value=b"x") as serialize:
            await publish_user_created_event(mock_db, mock_outbox, sample_user)

        mock_outbox.write_event_raw.assert_awaited_once()
        event = serialize.call_args.args[1]
        assert event.account_snapshot.display_name == "李 小龍"
        assert event.account_snapshot.first_name is None
        assert event.account_snapshot.last_name is None
        call_kwargs = mock_outbox.write_event_raw.call_args.kwargs

        assert call_kwargs["db"] == mock_db
        assert call_kwargs["params"].aggregate_type == "user"
        assert call_kwargs["params"].aggregate_id == str(sample_user.id)
        assert call_kwargs["params"].event_type == "user-auth.cdc.account-updated.v1"
        assert call_kwargs["params"].correlation_id == str(sample_user.id)

    @pytest.mark.asyncio
    async def test_handles_none_optional_fields(self) -> None:
        """Handles None values for optional user fields."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event_raw = AsyncMock(return_value=uuid.uuid4())

        user = MagicMock(spec=Account)
        user.id = uuid.uuid4()
        user.email = "test@example.com"
        user.display_name = None
        user.first_name = None
        user.last_name = None
        user.is_active = True
        user.created_at = datetime.now(UTC)
        user.updated_at = datetime.now(UTC)

        with patch("user_auth_service.events.publishers.kafka_client.serialize", return_value=b"x"):
            await publish_user_created_event(mock_db, mock_outbox, user)

        mock_outbox.write_event_raw.assert_awaited_once()


class TestPublishUserUpdatedEvent:
    """Tests for publish_user_updated_event function."""

    @pytest.fixture
    def sample_user(self) -> MagicMock:
        """Create a sample user for testing."""
        user = MagicMock(spec=Account)
        user.id = uuid.uuid4()
        user.email = "updated@example.com"
        user.display_name = "Updated Account"
        user.first_name = "Updated"
        user.last_name = "Account"
        user.is_active = True
        user.created_at = datetime.now(UTC)
        user.updated_at = datetime.now(UTC)
        return user

    @pytest.mark.asyncio
    async def test_publishes_updated_event(self, sample_user: Account) -> None:
        """Publishes user.updated.v1 event via outbox."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event_raw = AsyncMock(return_value=uuid.uuid4())

        with patch("user_auth_service.events.publishers.kafka_client.serialize", return_value=b"x"):
            await publish_user_updated_event(mock_db, mock_outbox, sample_user)

        mock_outbox.write_event_raw.assert_awaited_once()
        call_kwargs = mock_outbox.write_event_raw.call_args.kwargs

        assert call_kwargs["params"].event_type == "user-auth.cdc.account-updated.v1"
        assert call_kwargs["params"].aggregate_type == "user"


class TestPublishUserDeletedEvent:
    """Tests for publish_user_deleted_event function."""

    @pytest.mark.asyncio
    async def test_publishes_deleted_event(self) -> None:
        """Publishes user.deleted.v1 event via outbox."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event_raw = AsyncMock(return_value=uuid.uuid4())

        user_id = uuid.uuid4()

        with patch("user_auth_service.events.publishers.kafka_client.serialize", return_value=b"x"):
            await publish_user_deleted_event(mock_db, mock_outbox, user_id)

        mock_outbox.write_event_raw.assert_awaited_once()
        call_kwargs = mock_outbox.write_event_raw.call_args.kwargs

        assert call_kwargs["db"] == mock_db
        assert call_kwargs["params"].aggregate_type == "user"
        assert call_kwargs["params"].aggregate_id == str(user_id)
        assert call_kwargs["params"].event_type == "user-auth.cdc.account-deleted.v1"
        assert call_kwargs["params"].correlation_id == str(user_id)


class TestPublishAccessTokenRevokedEvent:
    """Tests for the durable access-token revocation fact."""

    @pytest.mark.asyncio
    async def test_serializes_exact_event_and_outbox_metadata(self) -> None:
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        user_id = uuid.uuid4()
        jti = uuid.uuid4()
        session_family_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + timedelta(minutes=5)

        with patch("user_auth_service.events.publishers.kafka_client.serialize", return_value=b"encoded") as serialize:
            await publish_access_token_revoked_event(
                mock_db,
                mock_outbox,
                user_id=user_id,
                jti=jti,
                expires_at=expires_at,
                session_family_id=session_family_id,
            )

        topic, event = serialize.call_args.args
        assert topic == "user-auth.fct.access-token-revoked.v1"
        assert event.user_id == str(user_id)
        assert event.jti == str(jti)
        assert event.expires_at == expires_at
        assert event.session_family_id == str(session_family_id)
        assert event.metadata.source_service == "user-auth-service"
        assert event.metadata.event_id
        assert event.metadata.timestamp

        kwargs = mock_outbox.write_event_raw.await_args.kwargs
        assert kwargs["db"] is mock_db
        assert kwargs["payload"] == b"encoded"
        assert kwargs["params"].aggregate_type == "user"
        assert kwargs["params"].aggregate_id == str(user_id)
        assert kwargs["params"].event_type == topic
        assert kwargs["params"].correlation_id == str(jti)

    @pytest.mark.asyncio
    async def test_legacy_jti_event_omits_session_family(self) -> None:
        mock_outbox = AsyncMock()
        with patch("user_auth_service.events.publishers.kafka_client.serialize", return_value=b"encoded") as serialize:
            await publish_access_token_revoked_event(
                create_mock_session(),
                mock_outbox,
                user_id=uuid.uuid4(),
                jti=uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                session_family_id=None,
            )

        event = serialize.call_args.args[1]
        assert event.session_family_id is None

    @pytest.mark.asyncio
    async def test_rejects_event_without_revocation_target(self) -> None:
        mock_outbox = AsyncMock()
        with (
            patch("user_auth_service.events.publishers.kafka_client.serialize") as serialize,
            pytest.raises(ValueError, match="jti or session_family_id is required"),
        ):
            await publish_access_token_revoked_event(
                create_mock_session(),
                mock_outbox,
                user_id=uuid.uuid4(),
                jti=None,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                session_family_id=None,
            )

        serialize.assert_not_called()
        mock_outbox.write_event_raw.assert_not_awaited()

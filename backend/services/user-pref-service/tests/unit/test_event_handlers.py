"""Unit tests for user_pref_service.events.upstream_cdc module."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.user.auth.v1 import AccountDeleted
from nohiki.user.upload.v1 import UploadDeleted
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from user_pref_service.events.upstream_cdc import (
    handle_attachment_deleted,
    handle_user_deleted,
)


def _make_context(*, db_session: AsyncMock | None = None, outbox: AsyncMock | None = None) -> MessageContext:
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


class TestHandleAttachmentDeleted:
    """Tests for handle_attachment_deleted event handler."""

    @pytest.mark.asyncio
    async def test_publishes_profiles_reloaded_after_bulk_revision_update(self) -> None:
        """Publishes refreshed parents rather than stale pre-deletion snapshots."""
        upload_id = str(uuid.uuid4())
        message = UploadDeleted(upload_id=upload_id, user_id="user-456")

        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        affected_profile_1 = MagicMock(id=uuid.uuid4())
        affected_profile_2 = MagicMock(id=uuid.uuid4())
        refreshed_profile_1 = MagicMock(id=affected_profile_1.id)
        refreshed_profile_2 = MagicMock(id=affected_profile_2.id)

        with (
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.get_profiles_with_attachment"
            ) as mock_get_profiles,
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.remove_attachment_from_all_profiles"
            ) as mock_remove,
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.get_profiles_by_ids"
            ) as mock_get_profiles_by_ids,
            patch("user_pref_service.events.upstream_cdc.publish_profile_updated_batch") as mock_publish,
        ):
            mock_get_profiles.return_value = [
                affected_profile_1,
                affected_profile_2,
            ]
            mock_remove.return_value = 2
            mock_get_profiles_by_ids.return_value = [
                refreshed_profile_1,
                refreshed_profile_2,
            ]

            await handle_attachment_deleted(message, context)

            mock_get_profiles.assert_awaited_once_with(mock_db, uuid.UUID(upload_id))
            mock_remove.assert_awaited_once_with(mock_db, uuid.UUID(upload_id))
            mock_get_profiles_by_ids.assert_awaited_once_with(
                mock_db,
                {affected_profile_1.id, affected_profile_2.id},
            )
            mock_publish.assert_awaited_once_with(
                mock_db,
                mock_outbox,
                [refreshed_profile_1, refreshed_profile_2],
            )

    @pytest.mark.asyncio
    async def test_rejects_when_no_upload_id(self) -> None:
        """Rejects a destructive event when upload_id is empty."""
        message = UploadDeleted(upload_id="", user_id="user-456")
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.remove_attachment_from_all_profiles"
            ) as mock_remove,
            pytest.raises(ValueError, match="upload_id"),
        ):
            await handle_attachment_deleted(message, context)

        mock_remove.assert_not_awaited()


class TestHandleUserDeleted:
    """Tests for handle_user_deleted event handler."""

    @pytest.fixture(autouse=True)
    def _mock_profile_vector_cleanup(self) -> object:
        with (
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.get_profile_ids_for_user",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "user_pref_service.events.upstream_cdc.delete_profile_points",
                new_callable=AsyncMock,
            ) as mock,
        ):
            yield mock

    @pytest.mark.asyncio
    async def test_bulk_qdrant_cleanup_precedes_database_deletion(self) -> None:
        user_id = uuid.uuid4()
        profile_ids = [uuid.uuid4(), uuid.uuid4()]
        context = _make_context(db_session=create_mock_session())
        calls: list[str] = []

        async def qdrant(*_args: object) -> None:
            calls.append("qdrant")

        async def profiles(*_args: object) -> int:
            calls.append("profiles")
            return 2

        async def settings(*_args: object) -> int:
            calls.append("settings")
            return 0

        with (
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.get_profile_ids_for_user",
                new_callable=AsyncMock,
                return_value=profile_ids,
            ),
            patch(
                "user_pref_service.events.upstream_cdc.delete_profile_points",
                side_effect=qdrant,
            ) as remove,
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.delete_user_profiles",
                side_effect=profiles,
            ),
            patch(
                "user_pref_service.events.upstream_cdc.settings_service.delete_user_settings",
                side_effect=settings,
            ),
        ):
            await handle_user_deleted(AccountDeleted(user_id=str(user_id)), context)

        remove.assert_awaited_once_with(profile_ids)
        assert calls == ["qdrant", "profiles", "settings"]

    @pytest.mark.asyncio
    async def test_qdrant_failure_suppresses_account_database_deletion(self) -> None:
        user_id = uuid.uuid4()
        context = _make_context(db_session=create_mock_session())
        with (
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.get_profile_ids_for_user",
                new_callable=AsyncMock,
                return_value=[uuid.uuid4()],
            ),
            patch(
                "user_pref_service.events.upstream_cdc.delete_profile_points",
                new_callable=AsyncMock,
                side_effect=RuntimeError("qdrant unavailable"),
            ),
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.delete_user_profiles",
                new_callable=AsyncMock,
            ) as delete_profiles,
            patch(
                "user_pref_service.events.upstream_cdc.settings_service.delete_user_settings",
                new_callable=AsyncMock,
            ) as delete_settings,
            pytest.raises(RuntimeError, match="qdrant unavailable"),
        ):
            await handle_user_deleted(AccountDeleted(user_id=str(user_id)), context)

        delete_profiles.assert_not_awaited()
        delete_settings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_account_does_not_issue_transport_delete(self) -> None:
        context = _make_context(db_session=create_mock_session())
        with (
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.get_profile_ids_for_user",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "user_pref_service.events.upstream_cdc.delete_profile_points",
                new_callable=AsyncMock,
            ) as remove,
            patch(
                "user_pref_service.events.upstream_cdc.profile_service.delete_user_profiles",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "user_pref_service.events.upstream_cdc.settings_service.delete_user_settings",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            await handle_user_deleted(AccountDeleted(user_id=str(uuid.uuid4())), context)

        remove.assert_awaited_once_with([])

    @pytest.mark.asyncio
    async def test_deletes_all_user_profiles(self) -> None:
        """Deletes all profiles for deleted user."""
        user_id = str(uuid.uuid4())
        message = AccountDeleted(user_id=user_id)

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch("user_pref_service.events.upstream_cdc.profile_service.delete_user_profiles") as mock_delete:
            mock_delete.return_value = 5

            await handle_user_deleted(message, context)

            mock_delete.assert_awaited_once_with(mock_db, uuid.UUID(user_id))

    @pytest.mark.asyncio
    async def test_rejects_when_no_user_id(self) -> None:
        """Rejects a destructive event when user_id is empty."""
        message = AccountDeleted(user_id="")
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("user_pref_service.events.upstream_cdc.profile_service.delete_user_profiles") as mock_delete,
            pytest.raises(ValueError, match="user_id"),
        ):
            await handle_user_deleted(message, context)

        mock_delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handles_user_with_no_profiles(self) -> None:
        """Handles case where user has no profiles gracefully."""
        user_id = str(uuid.uuid4())
        message = AccountDeleted(user_id=user_id)

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch("user_pref_service.events.upstream_cdc.profile_service.delete_user_profiles") as mock_delete:
            mock_delete.return_value = 0

            await handle_user_deleted(message, context)

            mock_delete.assert_awaited_once()

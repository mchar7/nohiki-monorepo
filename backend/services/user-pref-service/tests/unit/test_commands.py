"""Unit tests for commands.py event handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_fastapi_utils.errors import NotFoundError
from nohiki_kafka_client import MessageContext
from user_pref_service.events.commands import (
    _collect_canonical_skill_ids,
    handle_pref_attach_upload_requested,
    handle_pref_create_requested,
    handle_pref_delete_requested,
    handle_pref_detach_upload_requested,
    handle_pref_feature_importance_update_requested,
    handle_pref_update_requested,
    handle_user_pref_settings_update_requested,
)


def _make_context(
    *,
    db_session: AsyncMock | None = None,
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


def _make_create_message(
    *,
    user_id: str | None = None,
    request_id: str | None = None,
) -> MagicMock:
    """Build a mock PrefCreateRequested message."""
    msg = MagicMock()
    msg.user_id = user_id or str(uuid4())
    msg.request_id = request_id or str(uuid4())
    msg.metadata.correlation_id = "corr-1"
    msg.user_skills = ["python"]
    msg.required_skills = ["java"]
    msg.preferred_skills = []
    msg.physical_locations = []
    msg.search_keywords = ["developer"]
    msg.work_arrangements = ["REMOTE"]
    return msg


def _make_update_message(
    *,
    user_id: str | None = None,
    pref_id: str | None = None,
) -> MagicMock:
    """Build a mock PrefUpdateRequested message."""
    msg = MagicMock()
    msg.user_id = user_id or str(uuid4())
    msg.pref_id = pref_id or str(uuid4())
    msg.request_id = str(uuid4())
    msg.metadata.correlation_id = "corr-2"
    msg.user_skills = []
    msg.required_skills = []
    msg.preferred_skills = []
    msg.physical_locations = []
    msg.search_keywords = []
    return msg


class TestHandlePrefCreateRequested:
    """Tests for handle_pref_create_requested command handler."""

    @pytest.mark.asyncio
    async def test_rejects_create_without_work_arrangements(self) -> None:
        message = _make_create_message()
        message.work_arrangements = []
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.logger") as mock_logger,
        ):
            mock_ps.get_profile_by_request_id = AsyncMock(return_value=None)
            mock_ps.create_profile = AsyncMock()

            await handle_pref_create_requested(message, context)

            mock_ps.get_profile_by_request_id.assert_not_called()
            mock_ps.create_profile.assert_not_called()
            mock_logger.warning.assert_called_once_with(
                "Rejecting pref create without work arrangements",
                request_id=message.request_id,
                user_id=message.user_id,
            )

    @pytest.mark.asyncio
    async def test_creates_profile_when_work_arrangements_present(self) -> None:
        message = _make_create_message()
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)
        mock_profile = MagicMock()
        mock_profile.id = uuid4()

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands.request_skill_normalization",
                new_callable=AsyncMock,
            ) as mock_skill,
        ):
            mock_ps.get_profile_by_request_id = AsyncMock(return_value=None)
            mock_ps.create_profile = AsyncMock(return_value=mock_profile)

            await handle_pref_create_requested(message, context)

            mock_ps.create_profile.assert_awaited_once_with(mock_db, UUID(message.user_id), message)
            mock_skill.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_idempotent_skip_when_fully_processed(self) -> None:
        """Skips when request_id already fully processed (enrichment complete)."""
        message = _make_create_message()
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        existing = MagicMock()
        existing.is_enrichment_complete = True

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.logger") as mock_logger,
        ):
            mock_ps.get_profile_by_request_id = AsyncMock(return_value=existing)

            await handle_pref_create_requested(message, context)

            mock_logger.info.assert_any_call(
                "Command already fully processed",
                request_id=message.request_id,
            )

    @pytest.mark.asyncio
    async def test_retriggers_enrichment_when_incomplete(self) -> None:
        """Re-triggers enrichment when profile exists but enrichment incomplete."""
        message = _make_create_message()
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        existing = MagicMock()
        existing.is_enrichment_complete = False
        existing.id = uuid4()

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands.request_skill_normalization",
                new_callable=AsyncMock,
            ) as mock_skill,
        ):
            mock_ps.get_profile_by_request_id = AsyncMock(return_value=existing)

            await handle_pref_create_requested(message, context)

            mock_skill.assert_awaited_once()
            mock_ps.create_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_profile_and_dispatches_ordered_canonical_skills(
        self,
    ) -> None:
        """Picker IDs are preserved and dispatched through the canonical field."""
        message = _make_create_message()
        first, second, third = (str(uuid4()) for _ in range(3))
        message.user_skills = [first, second]
        message.required_skills = [first]
        message.preferred_skills = [third]
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db, outbox=MagicMock())
        mock_profile = MagicMock(id=uuid4())

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands.request_skill_normalization",
                new_callable=AsyncMock,
            ) as mock_skill,
        ):
            mock_ps.get_profile_by_request_id = AsyncMock(return_value=None)
            mock_ps.create_profile = AsyncMock(return_value=mock_profile)
            await handle_pref_create_requested(message, context)

        mock_skill.assert_awaited_once_with(
            canonical_skill_ids=[first, second, third],
            profile_id=mock_profile.id,
            correlation_id="corr-1",
            action="create",
        )

    @pytest.mark.asyncio
    async def test_requests_pref_name_embedding_when_no_skills_or_keywords(
        self,
    ) -> None:
        """Profiles without skills or keywords embed their name before publication."""
        message = _make_create_message()
        message.user_skills = []
        message.required_skills = []
        message.preferred_skills = []
        message.search_keywords = []
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_profile = MagicMock()
        mock_profile.id = uuid4()
        mock_profile.is_enrichment_complete = False
        mock_profile.pref_name = "Fallback Profile"

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands._request_profile_embedding",
                new_callable=AsyncMock,
            ) as mock_embedding,
        ):
            mock_ps.get_profile_by_request_id = AsyncMock(return_value=None)
            mock_ps.create_profile = AsyncMock(return_value=mock_profile)

            await handle_pref_create_requested(message, context)

            mock_embedding.assert_awaited_once_with(str(mock_profile.id), "Fallback Profile", action="create")
            assert mock_profile.is_enrichment_complete is False


class TestHandlePrefUpdateRequested:
    """Tests for handle_pref_update_requested command handler."""

    @pytest.mark.asyncio
    async def test_skips_when_profile_not_found(self) -> None:
        """Skips when profile not found (stale event)."""
        message = _make_update_message()
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.logger") as mock_logger,
        ):
            mock_ps.get_profile_by_id = AsyncMock(side_effect=NotFoundError("not found"))

            await handle_pref_update_requested(message, context)

            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_user_does_not_own_profile(self) -> None:
        """Skips when user doesn't own the profile."""
        user_id = uuid4()
        other_user_id = uuid4()
        pref_id = uuid4()
        message = _make_update_message(user_id=str(user_id), pref_id=str(pref_id))
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_profile = MagicMock()
        mock_profile.user_id = other_user_id

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.logger") as mock_logger,
        ):
            mock_ps.get_profile_by_id = AsyncMock(return_value=mock_profile)

            await handle_pref_update_requested(message, context)

            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_ordered_canonical_skills_on_update(self) -> None:
        """Update preserves picker IDs instead of reinterpreting them as labels."""
        user_id, pref_id = uuid4(), uuid4()
        first, second = str(uuid4()), str(uuid4())
        message = _make_update_message(user_id=str(user_id), pref_id=str(pref_id))
        message.user_skills = [first]
        message.required_skills = [first, second]
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db, outbox=MagicMock())
        mock_profile = MagicMock(id=pref_id, user_id=user_id, is_enrichment_complete=True)

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands.request_skill_normalization",
                new_callable=AsyncMock,
            ) as mock_skill,
        ):
            mock_ps.get_profile_by_id = AsyncMock(return_value=mock_profile)
            mock_ps.update_profile = AsyncMock(return_value=mock_profile)
            await handle_pref_update_requested(message, context)

        mock_skill.assert_awaited_once_with(
            canonical_skill_ids=[first, second],
            profile_id=pref_id,
            correlation_id="corr-2",
            action="update",
        )
        assert mock_profile.is_enrichment_complete is False

    @pytest.mark.asyncio
    async def test_requests_pref_name_embedding_when_no_skills_or_keywords(
        self,
    ) -> None:
        """Updates without skills or keywords embed the name before publication."""
        user_id = uuid4()
        pref_id = uuid4()
        message = _make_update_message(user_id=str(user_id), pref_id=str(pref_id))
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_profile = MagicMock()
        mock_profile.id = pref_id
        mock_profile.user_id = user_id
        mock_profile.is_enrichment_complete = False
        mock_profile.pref_name = "Fallback Profile"

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands._request_profile_embedding",
                new_callable=AsyncMock,
            ) as mock_embedding,
            patch(
                "user_pref_service.events.commands.publish_profile_updated_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_ps.get_profile_by_id = AsyncMock(return_value=mock_profile)
            mock_ps.update_profile = AsyncMock(return_value=mock_profile)

            await handle_pref_update_requested(message, context)

            mock_embedding.assert_awaited_once_with(str(mock_profile.id), "Fallback Profile", action="update")
            mock_publish.assert_not_awaited()
            assert mock_profile.is_enrichment_complete is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("updated_fields", [["is_active"], ["pref_name"]], ids=["unrelated", "name-only"])
    async def test_patch_embedding_uses_persisted_semantic_state_without_skill_normalization(
        self, updated_fields: list[str]
    ) -> None:
        """Non-skill patches retain persisted keywords and canonical skill names in QUERY text."""
        user_id, pref_id = uuid4(), uuid4()
        message = _make_update_message(user_id=str(user_id), pref_id=str(pref_id))
        message.updated_fields = updated_fields
        message.pref_name = "Renamed Profile"
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        mock_profile = MagicMock(id=pref_id, user_id=user_id, is_enrichment_complete=True)
        mock_profile.pref_name = "Renamed Profile"
        mock_profile.search_keywords = ["Python", "distributed systems"]
        mock_profile.user_skills_data = [
            {"skill_name": "Kubernetes"},
            {"skill_name": "PYTHON"},
        ]
        mock_profile.semantic_content_generation = 4

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands.request_skill_normalization",
                new_callable=AsyncMock,
            ) as mock_skill,
            patch(
                "user_pref_service.events.commands._request_profile_embedding",
                new_callable=AsyncMock,
            ) as mock_embedding,
        ):
            mock_ps.get_profile_by_id = AsyncMock(return_value=mock_profile)
            mock_ps.update_profile = AsyncMock(return_value=mock_profile)

            await handle_pref_update_requested(message, context)

        mock_skill.assert_not_awaited()
        mock_embedding.assert_awaited_once()
        embedding_call = mock_embedding.await_args
        assert embedding_call is not None
        assert embedding_call.args == (
            str(mock_profile.id),
            "Renamed Profile Python distributed systems Kubernetes",
        )
        assert embedding_call.kwargs["action"] == "update"
        assert mock_profile.is_enrichment_complete is False


class TestHandlePrefDeleteRequested:
    """Tests for handle_pref_delete_requested command handler."""

    @pytest.fixture(autouse=True)
    def _mock_qdrant_transport(self) -> object:
        with patch(
            "user_pref_service.events.commands.delete_profile_points",
            new_callable=AsyncMock,
        ) as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_idempotent_when_already_deleted(self) -> None:
        """Skips when profile already deleted (idempotent)."""
        msg = MagicMock()
        msg.request_id = "req-3"
        msg.user_id = str(uuid4())
        msg.pref_id = str(uuid4())
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.logger") as mock_logger,
        ):
            mock_ps.get_profile_by_id_optional = AsyncMock(return_value=None)

            await handle_pref_delete_requested(msg, context)

            mock_logger.info.assert_any_call(
                "Profile already deleted (idempotent)",
                pref_id=msg.pref_id,
            )

    @pytest.mark.asyncio
    async def test_skips_when_user_does_not_own_profile(self) -> None:
        """Skips when user doesn't own the profile."""
        user_id = uuid4()
        other_user_id = uuid4()
        msg = MagicMock()
        msg.request_id = "req-3"
        msg.user_id = str(user_id)
        msg.pref_id = str(uuid4())
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_profile = MagicMock()
        mock_profile.user_id = other_user_id

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.logger") as mock_logger,
        ):
            mock_ps.get_profile_by_id_optional = AsyncMock(return_value=mock_profile)

            await handle_pref_delete_requested(msg, context)

            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_deletes_and_publishes(self) -> None:
        """Deletes profile and publishes deleted event."""
        user_id = uuid4()
        pref_id = uuid4()
        msg = MagicMock()
        msg.request_id = "req-3"
        msg.user_id = str(user_id)
        msg.pref_id = str(pref_id)
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_profile = MagicMock()
        mock_profile.user_id = user_id

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands.publish_profile_deleted_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_ps.get_profile_by_id_optional = AsyncMock(return_value=mock_profile)
            mock_ps.delete_profile = AsyncMock()

            await handle_pref_delete_requested(msg, context)

            mock_ps.delete_profile.assert_awaited_once()
            mock_publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_qdrant_delete_precedes_sql_delete_and_cdc(self) -> None:
        user_id, pref_id = uuid4(), uuid4()
        message = MagicMock(request_id="req", user_id=str(user_id), pref_id=str(pref_id))
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        profile = MagicMock(user_id=user_id)
        calls: list[str] = []

        async def qdrant(*_args: object) -> None:
            calls.append("qdrant")

        async def sql(*_args: object) -> None:
            calls.append("sql")

        async def cdc(*_args: object) -> None:
            calls.append("cdc")

        with (
            patch("user_pref_service.events.commands.profile_service") as service,
            patch(
                "user_pref_service.events.commands.delete_profile_points",
                side_effect=qdrant,
            ),
            patch(
                "user_pref_service.events.commands.publish_profile_deleted_event",
                side_effect=cdc,
            ),
        ):
            service.get_profile_by_id_optional = AsyncMock(return_value=profile)
            service.delete_profile = AsyncMock(side_effect=sql)
            await handle_pref_delete_requested(message, context)

        assert calls == ["qdrant", "sql", "cdc"]

    @pytest.mark.asyncio
    async def test_qdrant_delete_failure_suppresses_sql_and_cdc(self) -> None:
        user_id, pref_id = uuid4(), uuid4()
        message = MagicMock(request_id="req", user_id=str(user_id), pref_id=str(pref_id))
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        with (
            patch("user_pref_service.events.commands.profile_service") as service,
            patch(
                "user_pref_service.events.commands.delete_profile_points",
                new_callable=AsyncMock,
                side_effect=RuntimeError("qdrant unavailable"),
            ),
            patch(
                "user_pref_service.events.commands.publish_profile_deleted_event",
                new_callable=AsyncMock,
            ) as publish,
        ):
            service.get_profile_by_id_optional = AsyncMock(return_value=MagicMock(user_id=user_id))
            service.delete_profile = AsyncMock()
            with pytest.raises(RuntimeError, match="qdrant unavailable"):
                await handle_pref_delete_requested(message, context)

        service.delete_profile.assert_not_awaited()
        publish.assert_not_awaited()


class TestHandlePrefAttachUploadRequested:
    """Tests for handle_pref_attach_upload_requested command handler."""

    @pytest.mark.asyncio
    async def test_skips_when_profile_not_found(self) -> None:
        """Skips when profile not found."""
        msg = MagicMock()
        msg.request_id = "req-4"
        msg.user_id = str(uuid4())
        msg.pref_id = str(uuid4())
        msg.upload_id = str(uuid4())
        msg.upload_category = 1
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.logger") as mock_logger,
        ):
            mock_ps.get_profile_by_id = AsyncMock(side_effect=NotFoundError("not found"))

            await handle_pref_attach_upload_requested(msg, context)

            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_attaches_and_publishes(self) -> None:
        """Attaches upload and publishes updated event."""
        user_id = uuid4()
        pref_id = uuid4()
        msg = MagicMock()
        msg.request_id = "req-4"
        msg.user_id = str(user_id)
        msg.pref_id = str(pref_id)
        upload_id = uuid4()
        msg.upload_id = str(upload_id)
        msg.upload_category = 1
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        authorized_profile = MagicMock(user_id=user_id)
        refreshed_profile = MagicMock(user_id=user_id)

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands.publish_profile_updated_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_ps.get_profile_by_id = AsyncMock(side_effect=[authorized_profile, refreshed_profile])
            mock_ps.associate_attachment = AsyncMock()

            await handle_pref_attach_upload_requested(msg, context)

            mock_ps.associate_attachment.assert_awaited_once_with(mock_db, pref_id, upload_id, "example")
            mock_publish.assert_awaited_once_with(mock_db, mock_outbox, refreshed_profile)


class TestHandlePrefDetachUploadRequested:
    """Tests for handle_pref_detach_upload_requested command handler."""

    @pytest.mark.asyncio
    async def test_skips_when_profile_not_found(self) -> None:
        """Skips when profile not found."""
        msg = MagicMock()
        msg.request_id = "req-5"
        msg.user_id = str(uuid4())
        msg.pref_id = str(uuid4())
        msg.upload_id = str(uuid4())
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.logger") as mock_logger,
        ):
            mock_ps.get_profile_by_id = AsyncMock(side_effect=NotFoundError("not found"))

            await handle_pref_detach_upload_requested(msg, context)

            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_detaches_and_publishes(self) -> None:
        """Detaches upload and publishes updated event."""
        user_id = uuid4()
        pref_id = uuid4()
        msg = MagicMock()
        msg.request_id = "req-5"
        msg.user_id = str(user_id)
        msg.pref_id = str(pref_id)
        upload_id = uuid4()
        msg.upload_id = str(upload_id)
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        authorized_profile = MagicMock(user_id=user_id)
        refreshed_profile = MagicMock(user_id=user_id)

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch(
                "user_pref_service.events.commands.publish_profile_updated_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_ps.get_profile_by_id = AsyncMock(side_effect=[authorized_profile, refreshed_profile])
            mock_ps.disassociate_attachment = AsyncMock()

            await handle_pref_detach_upload_requested(msg, context)

            mock_ps.disassociate_attachment.assert_awaited_once_with(mock_db, pref_id, upload_id)
            mock_publish.assert_awaited_once_with(mock_db, mock_outbox, refreshed_profile)


class TestHandleUserPrefSettingsUpdateRequested:
    """Tests for handle_user_pref_settings_update_requested command handler."""

    @pytest.mark.asyncio
    async def test_creates_new_settings(self) -> None:
        """Creates new settings and publishes created event."""
        msg = MagicMock()
        msg.user_id = str(uuid4())
        msg.request_id = "req-6"
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_user_settings = MagicMock()

        with (
            patch("user_pref_service.events.commands.settings_service") as mock_ss,
            patch(
                "user_pref_service.events.commands.publish_settings_created_event",
                new_callable=AsyncMock,
            ) as mock_publish_created,
        ):
            mock_ss.upsert_user_settings = AsyncMock(return_value=(mock_user_settings, True))

            await handle_user_pref_settings_update_requested(msg, context)

            mock_publish_created.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_settings(self) -> None:
        """Updates existing settings and publishes updated event."""
        msg = MagicMock()
        msg.user_id = str(uuid4())
        msg.request_id = "req-6"
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_user_settings = MagicMock()

        with (
            patch("user_pref_service.events.commands.settings_service") as mock_ss,
            patch(
                "user_pref_service.events.commands.publish_settings_updated_event",
                new_callable=AsyncMock,
            ) as mock_publish_updated,
        ):
            mock_ss.upsert_user_settings = AsyncMock(return_value=(mock_user_settings, False))

            await handle_user_pref_settings_update_requested(msg, context)

            mock_publish_updated.assert_awaited_once()


class TestHandlePrefFeatureImportanceUpdateRequested:
    """Tests for handle_pref_feature_importance_update_requested command handler."""

    @pytest.mark.asyncio
    async def test_skips_when_user_does_not_own_profile(self) -> None:
        """Skips when user doesn't own the profile."""
        user_id = uuid4()
        other_user_id = uuid4()
        msg = MagicMock()
        msg.user_id = str(user_id)
        msg.pref_id = str(uuid4())
        msg.request_id = "req-7"
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_profile = MagicMock()
        mock_profile.user_id = other_user_id

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.logger") as mock_logger,
        ):
            mock_ps.get_profile_by_id = AsyncMock(return_value=mock_profile)

            await handle_pref_feature_importance_update_requested(msg, context)

            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_and_publishes(self) -> None:
        """Updates feature importance and publishes updated event."""
        user_id = uuid4()
        pref_id = uuid4()
        msg = MagicMock()
        msg.user_id = str(user_id)
        msg.pref_id = str(pref_id)
        msg.request_id = "req-7"
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        mock_profile = MagicMock()
        mock_profile.user_id = user_id

        with (
            patch("user_pref_service.events.commands.profile_service") as mock_ps,
            patch("user_pref_service.events.commands.settings_service") as mock_ss,
            patch(
                "user_pref_service.events.commands.publish_profile_updated_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_ps.get_profile_by_id = AsyncMock(return_value=mock_profile)
            mock_ss.update_profile_feature_importance = AsyncMock(return_value=mock_profile)

            await handle_pref_feature_importance_update_requested(msg, context)

            mock_ss.update_profile_feature_importance.assert_awaited_once()
            mock_publish.assert_awaited_once()


class TestCollectCanonicalSkillIds:
    """Tests for canonical picker-ID collection."""

    def test_deduplicates_in_first_seen_order(self) -> None:
        """IDs retain deterministic user, required, preferred order."""
        first, second, third = (str(uuid4()) for _ in range(3))
        msg = MagicMock(
            user_skills=[first, second],
            required_skills=[first],
            preferred_skills=[third, second],
        )

        assert _collect_canonical_skill_ids(msg) == [first, second, third]

    def test_returns_empty_when_no_skills(self) -> None:
        """No picker IDs yields no canonical dispatch."""
        msg = MagicMock(user_skills=[], required_skills=[], preferred_skills=[])

        assert _collect_canonical_skill_ids(msg) == []

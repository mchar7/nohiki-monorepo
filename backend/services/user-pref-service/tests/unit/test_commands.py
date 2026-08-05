"""Unit tests for commands.py event handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_fastapi_utils.errors import NotFoundError
from nohiki_kafka_client import MessageContext
from user_pref_service.db.models import PrefEnrichmentAction
from user_pref_service.events.commands import (
    _collect_canonical_skill_ids,
    _start_enrichment_saga,
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
        outbox=outbox or MagicMock(),
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


@pytest.mark.asyncio
async def test_start_saga_persists_identity_and_outbound_dispatch() -> None:
    message = _make_create_message()
    profile = MagicMock(
        id=uuid4(),
        user_id=uuid4(),
        semantic_content_generation=4,
        enrichment_terminal_status="failed",
    )
    db = create_mock_session()
    outbox = MagicMock()
    context = _make_context(db_session=db, outbox=outbox)
    saga = MagicMock()
    with (
        patch("user_pref_service.events.commands._profile_embedding_text", return_value="python platform"),
        patch("user_pref_service.events.commands._persist_embedding_identity", return_value="a" * 64),
        patch(
            "user_pref_service.events.commands.saga_service.create_enrichment_saga",
            new_callable=AsyncMock,
            return_value=saga,
        ) as create,
        patch(
            "user_pref_service.events.commands.saga_service.dispatch_next_step",
            new_callable=AsyncMock,
        ) as dispatch,
    ):
        await _start_enrichment_saga(
            context,
            profile=profile,
            message=message,
            action=PrefEnrichmentAction.CREATE,
            canonical_skill_ids=["python"],
        )

    assert profile.enrichment_terminal_status is None
    create.assert_awaited_once()
    dispatch.assert_awaited_once_with(db, outbox, saga)


class TestHandlePrefCreateRequested:
    @pytest.mark.asyncio
    async def test_rejects_missing_work_arrangements(self) -> None:
        message = _make_create_message()
        message.work_arrangements = []
        with patch("user_pref_service.events.commands.profile_service") as profiles:
            await handle_pref_create_requested(message, _make_context(db_session=create_mock_session()))
        profiles.create_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_request_owned_saga_before_dispatch(self) -> None:
        message = _make_create_message()
        profile = MagicMock(id=uuid4(), semantic_content_generation=1)
        with (
            patch(
                "user_pref_service.events.commands.saga_service.get_saga_by_request_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "user_pref_service.events.commands.profile_service.get_profile_by_request_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "user_pref_service.events.commands.profile_service.create_profile",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch(
                "user_pref_service.events.commands._start_enrichment_saga",
                new_callable=AsyncMock,
            ) as start,
        ):
            await handle_pref_create_requested(message, _make_context(db_session=create_mock_session()))

        assert start.await_args is not None
        kwargs = start.await_args.kwargs
        assert kwargs["message"] is message
        assert kwargs["canonical_skill_ids"] == ["python", "java"]

    @pytest.mark.asyncio
    async def test_no_skill_path_still_starts_embedding_saga(self) -> None:
        message = _make_create_message()
        message.user_skills = []
        message.required_skills = []
        profile = MagicMock(id=uuid4())
        with (
            patch(
                "user_pref_service.events.commands.saga_service.get_saga_by_request_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "user_pref_service.events.commands.profile_service.get_profile_by_request_id",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch(
                "user_pref_service.events.commands._start_enrichment_saga",
                new_callable=AsyncMock,
            ) as start,
        ):
            await handle_pref_create_requested(message, _make_context(db_session=create_mock_session()))
        assert start.await_args is not None
        assert start.await_args.kwargs["canonical_skill_ids"] == []

    @pytest.mark.asyncio
    async def test_request_redelivery_does_not_dispatch_again(self) -> None:
        message = _make_create_message()
        with (
            patch(
                "user_pref_service.events.commands.saga_service.get_saga_by_request_id",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "user_pref_service.events.commands._start_enrichment_saga",
                new_callable=AsyncMock,
            ) as start,
        ):
            await handle_pref_create_requested(message, _make_context(db_session=create_mock_session()))
        start.assert_not_awaited()


class TestHandlePrefUpdateRequested:
    @pytest.mark.asyncio
    async def test_supersedes_pending_saga_then_starts_update(self) -> None:
        user_id = uuid4()
        pref_id = uuid4()
        message = _make_update_message(user_id=str(user_id), pref_id=str(pref_id))
        message.updated_fields = ["pref_name"]
        profile = MagicMock(id=pref_id, user_id=user_id)
        updated = MagicMock(id=pref_id, user_id=user_id)
        order: list[str] = []
        with (
            patch(
                "user_pref_service.events.commands.saga_service.get_saga_by_request_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "user_pref_service.events.commands.profile_service.get_profile_by_id_for_update",
                new_callable=AsyncMock,
                return_value=profile,
            ) as locked_load,
            patch(
                "user_pref_service.events.commands.profile_service.get_profile_by_id",
                new_callable=AsyncMock,
                return_value=profile,
            ) as unlocked_load,
            patch(
                "user_pref_service.events.commands.saga_service.cancel_pending_enrichment",
                new_callable=AsyncMock,
                side_effect=lambda *_args, **_kwargs: order.append("cancel"),
            ),
            patch(
                "user_pref_service.events.commands.profile_service.update_profile",
                new_callable=AsyncMock,
                side_effect=lambda *_args, **_kwargs: (order.append("update"), updated)[1],
            ),
            patch(
                "user_pref_service.events.commands._start_enrichment_saga",
                new_callable=AsyncMock,
                side_effect=lambda *_args, **_kwargs: order.append("start"),
            ) as start,
        ):
            await handle_pref_update_requested(
                message,
                _make_context(db_session=create_mock_session(), outbox=MagicMock()),
            )

        assert order == ["cancel", "update", "start"]
        assert start.await_args is not None
        locked_load.assert_awaited_once_with(start.await_args.args[0].db_session, pref_id)
        unlocked_load.assert_not_awaited()
        assert start.await_args.kwargs["message"] is message

    @pytest.mark.asyncio
    async def test_missing_profile_does_not_start_saga(self) -> None:
        message = _make_update_message()
        with (
            patch(
                "user_pref_service.events.commands.saga_service.get_saga_by_request_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "user_pref_service.events.commands.profile_service.get_profile_by_id_for_update",
                new_callable=AsyncMock,
                side_effect=NotFoundError(resource="Profile", identifier=message.pref_id),
            ),
            patch(
                "user_pref_service.events.commands._start_enrichment_saga",
                new_callable=AsyncMock,
            ) as start,
        ):
            await handle_pref_update_requested(message, _make_context(db_session=create_mock_session()))
        start.assert_not_awaited()


class TestHandlePrefDeleteRequested:
    @pytest.mark.asyncio
    async def test_cancels_before_committed_delete_fact(self) -> None:
        user_id = uuid4()
        pref_id = uuid4()
        message = MagicMock(request_id=str(uuid4()), user_id=str(user_id), pref_id=str(pref_id))
        profile = MagicMock(user_id=user_id)
        order: list[str] = []
        with (
            patch(
                "user_pref_service.events.commands.profile_service.get_profile_by_id_optional",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch(
                "user_pref_service.events.commands.saga_service.cancel_pending_enrichment",
                new_callable=AsyncMock,
                side_effect=lambda *_args, **_kwargs: order.append("cancel"),
            ),
            patch(
                "user_pref_service.events.commands.profile_service.delete_profile",
                new_callable=AsyncMock,
                side_effect=lambda *_args, **_kwargs: order.append("delete"),
            ),
            patch(
                "user_pref_service.events.commands.publish_profile_deleted_event",
                new_callable=AsyncMock,
                side_effect=lambda *_args, **_kwargs: order.append("fact"),
            ),
        ):
            await handle_pref_delete_requested(
                message,
                _make_context(db_session=create_mock_session(), outbox=MagicMock()),
            )
        assert order == ["cancel", "delete", "fact"]


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

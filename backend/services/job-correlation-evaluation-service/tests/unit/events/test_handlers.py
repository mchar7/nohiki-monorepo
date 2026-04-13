"""Unit tests for events/handlers.py module."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


def _make_context(*, db_session: AsyncMock | None = None) -> MessageContext:
    """Build a ``MessageContext`` with injected db_session."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
    )


def _profile_snapshot(*, user_id: str = "test-user-id", revision: int = 1) -> MagicMock:
    """Build a profile snapshot carrying its source-owned CDC revision."""
    snapshot = MagicMock(user_id=user_id)
    snapshot.timestamps = MagicMock(updated_at=datetime(2026, 1, revision, tzinfo=UTC))
    return snapshot


class TestHandleJobStoreCreated:
    """Tests for handle_job_store_created handler."""

    @pytest.mark.asyncio
    async def test_returns_early_if_listing_missing(self) -> None:
        """Test that handler returns early if listing reference is missing."""
        from job_correlation_evaluation_service.events.handlers import (
            handle_job_store_created,
        )

        mock_message = MagicMock()
        mock_message.listing = None
        context = _make_context()

        await handle_job_store_created(mock_message, context)

    @pytest.mark.asyncio
    async def test_returns_early_if_snapshot_missing(self) -> None:
        """Test that handler returns early if listing_snapshot is missing."""
        from job_correlation_evaluation_service.events.handlers import (
            handle_job_store_created,
        )

        mock_message = MagicMock()
        mock_message.listing = MagicMock()
        mock_message.listing.listing_id = "test-id"
        mock_message.listing.listing_url = "https://example.com"
        mock_message.listing_snapshot = None
        context = _make_context()

        await handle_job_store_created(mock_message, context)

    @pytest.mark.asyncio
    async def test_calls_matcher_service(self) -> None:
        """Test that handler calls matcher service."""
        mock_message = MagicMock()
        mock_message.listing = MagicMock()
        mock_message.listing.listing_id = "test-id"
        mock_message.listing.listing_url = "https://example.com"
        mock_message.listing_snapshot = MagicMock()
        mock_message.metadata = MagicMock()
        mock_message.metadata.correlation_id = "test-correlation"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch("job_correlation_evaluation_service.events.handlers.JobMatcherService") as mock_matcher_cls:
            mock_matcher = AsyncMock()
            mock_matcher_cls.return_value = mock_matcher

            from job_correlation_evaluation_service.events.handlers import (
                handle_job_store_created,
            )

            await handle_job_store_created(mock_message, context)

            mock_matcher.match_job_to_profiles.assert_awaited_once()


class TestHandleProfileCreated:
    """Tests for handle_profile_created handler."""

    @pytest.mark.asyncio
    async def test_returns_early_if_snapshot_missing(self) -> None:
        """Test that handler returns early if pref_snapshot is missing."""
        from job_correlation_evaluation_service.events.handlers import (
            handle_profile_created,
        )

        mock_message = MagicMock()
        mock_message.pref_snapshot = None
        context = _make_context()

        await handle_profile_created(mock_message, context)

    @pytest.mark.asyncio
    async def test_triggers_backfill_when_enabled(self) -> None:
        """Test that backfill is triggered when enabled."""
        mock_message = MagicMock()
        mock_message.pref_id = "test-pref-id"
        mock_message.pref_snapshot = _profile_snapshot()
        mock_message.pref_snapshot.user_id = "test-user-id"
        mock_message.metadata = MagicMock(event_id="11111111-1111-4111-8111-111111111111")

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)
        context.correlation_id = "test-correlation"

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(return_value=True),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as mock_repo_cls,
            patch("job_correlation_evaluation_service.events.handlers.publish_backfill_request") as mock_publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as mock_settings,
        ):
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            mock_settings.backfill.enabled = True
            mock_publish.return_value = AsyncMock()

            from job_correlation_evaluation_service.events.handlers import (
                handle_profile_created,
            )

            await handle_profile_created(mock_message, context)

            mock_publish.assert_awaited_once()
            assert mock_publish.await_args is not None
            publish_db, request = mock_publish.await_args.args
            assert publish_db is mock_db
            assert request.pref_id == "test-pref-id"
            assert request.user_id == "test-user-id"
            assert request.correlation_id == "test-correlation"
            assert request.operation_id == "11111111-1111-4111-8111-111111111111"

    @pytest.mark.asyncio
    async def test_skips_backfill_when_disabled(self) -> None:
        """Test that backfill is skipped when disabled."""
        mock_message = MagicMock()
        mock_message.pref_id = "test-pref-id"
        mock_message.pref_snapshot = _profile_snapshot()
        mock_message.pref_snapshot.user_id = "test-user-id"
        mock_message.metadata = MagicMock(event_id="22222222-2222-4222-8222-222222222222")

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)
        context.correlation_id = "test-correlation"

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(return_value=True),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as mock_repo_cls,
            patch("job_correlation_evaluation_service.events.handlers.publish_backfill_request") as mock_publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as mock_settings,
        ):
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            mock_settings.backfill.enabled = False

            from job_correlation_evaluation_service.events.handlers import (
                handle_profile_created,
            )

            await handle_profile_created(mock_message, context)

            mock_publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stores_profile_before_backfill(self) -> None:
        """Test that profile is stored before triggering backfill."""
        mock_message = MagicMock()
        mock_message.pref_id = "test-pref-id"
        mock_message.pref_snapshot = _profile_snapshot()
        mock_message.pref_snapshot.user_id = "test-user-id"
        mock_message.metadata = MagicMock(event_id="33333333-3333-4333-8333-333333333333")

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)
        context.correlation_id = "test-correlation"

        call_order: list[str] = []

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(return_value=True),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as mock_repo_cls,
            patch("job_correlation_evaluation_service.events.handlers.publish_backfill_request") as mock_publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as mock_settings,
        ):

            def track_upsert_sync(*_args: object, **_kwargs: object) -> bool:
                call_order.append("upsert")
                return True

            def track_publish_sync(*_args: object, **_kwargs: object) -> str:
                call_order.append("publish")
                return "request-id"

            mock_repo = AsyncMock()
            mock_repo.upsert_profile.side_effect = track_upsert_sync
            mock_repo_cls.return_value = mock_repo

            mock_settings.backfill.enabled = True
            mock_publish.side_effect = track_publish_sync

            from job_correlation_evaluation_service.events.handlers import (
                handle_profile_created,
            )

            await handle_profile_created(mock_message, context)

            assert call_order == ["upsert", "publish"]


class TestHandleProfileUpdated:
    """Tests for handle_profile_updated handler."""

    @pytest.mark.asyncio
    async def test_returns_early_if_snapshot_missing(self) -> None:
        """Test that handler returns early if pref_snapshot is missing."""
        from job_correlation_evaluation_service.events.handlers import (
            handle_profile_updated,
        )

        mock_message = MagicMock()
        mock_message.pref_snapshot = None
        context = _make_context()

        await handle_profile_updated(mock_message, context)

    @pytest.mark.asyncio
    async def test_updates_profile_in_projection(self) -> None:
        """Test that handler updates profile in projection table."""
        mock_message = MagicMock()
        mock_message.pref_id = "test-pref-id"
        mock_message.pref_snapshot = _profile_snapshot()
        mock_message.pref_snapshot.user_id = "test-user-id"
        mock_message.metadata = MagicMock(event_id="44444444-4444-4444-8444-444444444444")

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)
        context.correlation_id = "test-correlation"

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(return_value=True),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as mock_repo_cls,
            patch("job_correlation_evaluation_service.events.handlers.publish_backfill_request") as mock_publish,
        ):
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.upsert_profile.return_value = True

            from job_correlation_evaluation_service.events.handlers import (
                handle_profile_updated,
            )

            await handle_profile_updated(mock_message, context)

            mock_repo.upsert_profile.assert_awaited_once_with(
                mock_message.pref_snapshot,
                mock_message.pref_snapshot.timestamps.updated_at,
            )
            mock_publish.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handler_name", ["handle_profile_created", "handle_profile_updated"])
    async def test_older_profile_revision_does_not_emit_backfill(self, handler_name: str) -> None:
        """Delayed create or update cannot regress state or trigger rescoring."""
        from job_correlation_evaluation_service.events import handlers

        message = MagicMock(
            pref_id="pref-id",
            pref_snapshot=_profile_snapshot(revision=1),
            metadata=MagicMock(event_id="stale-profile-event"),
        )
        db = create_mock_session()
        context = _make_context(db_session=db)

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(return_value=True),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as repository_class,
            patch(
                "job_correlation_evaluation_service.events.handlers.publish_backfill_request",
                new=AsyncMock(),
            ) as publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as handler_settings,
        ):
            repository = AsyncMock()
            repository.upsert_profile.return_value = False
            repository_class.return_value = repository
            handler_settings.backfill.enabled = True

            await getattr(handlers, handler_name)(message, context)

        repository.upsert_profile.assert_awaited_once_with(
            message.pref_snapshot,
            message.pref_snapshot.timestamps.updated_at,
        )
        publish.assert_not_awaited()
        db.commit.assert_awaited_once()
        repository.invalidate_cache.assert_not_awaited()


class TestHandleJobStoreDeleted:
    """Tests for handle_job_store_deleted handler."""

    @pytest.mark.asyncio
    async def test_handles_deletion(self) -> None:
        """Test that handler handles job deletion."""
        from job_correlation_evaluation_service.events.handlers import (
            handle_job_store_deleted,
        )

        mock_message = MagicMock()
        mock_message.listing_id = "550e8400-e29b-41d4-a716-446655440000"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)
        context.correlation_id = "test-correlation"

        with patch("job_correlation_evaluation_service.events.handlers.JobMatcherService") as mock_matcher_cls:
            mock_matcher_instance = MagicMock()
            mock_matcher_instance.dismiss_matches_for_deleted_job = AsyncMock(return_value=5)
            mock_matcher_cls.return_value = mock_matcher_instance

            await handle_job_store_deleted(mock_message, context)

            mock_matcher_instance.dismiss_matches_for_deleted_job.assert_awaited_once()


class TestHandleProfileDeleted:
    """Tests for ordered profile deletion tombstones."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("changed", [False, True])
    async def test_commits_tombstone_and_invalidates_only_when_newer(self, *, changed: bool) -> None:
        """Stale deletes preserve cache; advancing deletes hide the profile."""
        from job_correlation_evaluation_service.events.handlers import (
            handle_profile_deleted,
        )

        revision = datetime(2026, 1, 3, tzinfo=UTC)
        message = MagicMock(
            pref_id="550e8400-e29b-41d4-a716-446655440000",
            user_id="660e8400-e29b-41d4-a716-446655440000",
            metadata=MagicMock(event_id="delete-event", timestamp=revision),
        )
        db = create_mock_session()
        context = _make_context(db_session=db)

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(return_value=True),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as repository_class,
        ):
            repository = AsyncMock()
            repository.tombstone_profile.return_value = changed
            repository_class.return_value = repository

            await handle_profile_deleted(message, context)

        repository.tombstone_profile.assert_awaited_once_with(
            UUID(message.pref_id),
            UUID(message.user_id),
            revision,
        )
        db.commit.assert_awaited_once()
        if changed:
            repository.invalidate_cache.assert_awaited_once()
        else:
            repository.invalidate_cache.assert_not_awaited()


class TestInputEventRedelivery:
    """Defend durable input claims at correlation side-effect boundaries."""

    @pytest.mark.asyncio
    async def test_force_rescore_replay_emits_no_second_terminal_event(self) -> None:
        """A committed ListingUpdated event reaches persist/outbox matching only once."""
        from job_correlation_evaluation_service.events.handlers import (
            handle_job_store_updated,
        )

        event_id = "55555555-5555-4555-8555-555555555555"
        message = MagicMock(
            listing_id="listing-id",
            listing_snapshot=MagicMock(skills_embedding=[0.1], skill_requirements=[]),
            metadata=MagicMock(event_id=event_id, correlation_id="correlation-id"),
        )
        db = create_mock_session()
        context = _make_context(db_session=db)

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(side_effect=[True, False]),
            ) as claim,
            patch("job_correlation_evaluation_service.events.handlers.JobMatcherService") as matcher_class,
        ):
            matcher = MagicMock()
            matcher.match_job_to_profiles = AsyncMock(return_value=1)
            matcher_class.return_value = matcher

            await handle_job_store_updated(message, context)
            await handle_job_store_updated(message, context)

        assert claim.await_args_list[0].args == (
            db,
            event_id,
            "handle_job_store_updated",
        )
        assert claim.await_count == 2
        matcher.match_job_to_profiles.assert_awaited_once_with(
            db=db,
            job=message.listing_snapshot,
            correlation_id="correlation-id",
            force_rescore=True,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handler_name", "force_rescore"),
        [
            ("handle_profile_created", False),
            ("handle_profile_updated", True),
        ],
    )
    async def test_profile_replay_writes_one_deterministic_backfill_command(
        self, handler_name: str, *, force_rescore: bool
    ) -> None:
        """Projection, claim, and stable outbox command commit once per input event."""
        from job_correlation_evaluation_service.events import handlers

        event_id = "66666666-6666-4666-8666-666666666666"
        message = MagicMock(
            pref_id="pref-id",
            pref_snapshot=_profile_snapshot(user_id="user-id"),
            metadata=MagicMock(event_id=event_id, version="v1"),
        )
        db = create_mock_session()
        context = _make_context(db_session=db)
        context.correlation_id = "correlation-id"

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(side_effect=[True, False]),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as repository_class,
            patch(
                "job_correlation_evaluation_service.events.handlers.publish_backfill_request",
                new=AsyncMock(),
            ) as publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as handler_settings,
        ):
            repository = AsyncMock()
            repository_class.return_value = repository
            handler_settings.backfill.enabled = True
            handler = getattr(handlers, handler_name)

            await handler(message, context)
            await handler(message, context)

        repository.upsert_profile.assert_awaited_once_with(
            message.pref_snapshot,
            message.pref_snapshot.timestamps.updated_at,
        )
        publish.assert_awaited_once()
        assert publish.await_args is not None
        publish_db, request = publish.await_args.args
        assert publish_db is db
        assert request.pref_id == "pref-id"
        assert request.user_id == "user-id"
        assert request.correlation_id == "correlation-id"
        assert request.operation_id == event_id
        assert request.force_rescore is force_rescore
        db.commit.assert_awaited_once()
        repository.invalidate_cache.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
    async def test_post_commit_failure_redelivery_remains_idempotent(self, failure_type: type[BaseException]) -> None:
        """Failure after durable commit cannot duplicate projection or backfill outbox."""
        from job_correlation_evaluation_service.events.handlers import (
            handle_profile_created,
        )

        event_id = "77777777-7777-4777-8777-777777777777"
        message = MagicMock(
            pref_id="pref-id",
            pref_snapshot=_profile_snapshot(user_id="user-id"),
            metadata=MagicMock(event_id=event_id, version="v1"),
        )
        db = create_mock_session()
        context = _make_context(db_session=db)

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(side_effect=[True, False]),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as repository_class,
            patch(
                "job_correlation_evaluation_service.events.handlers.publish_backfill_request",
                new=AsyncMock(),
            ) as publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as handler_settings,
        ):
            repository = AsyncMock()
            repository.invalidate_cache.side_effect = failure_type("interrupted after commit")
            repository_class.return_value = repository
            handler_settings.backfill.enabled = True

            with pytest.raises(failure_type, match="interrupted after commit"):
                await handle_profile_created(message, context)
            await handle_profile_created(message, context)

        repository.upsert_profile.assert_awaited_once()
        publish.assert_awaited_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_backfill_wal_failure_prevents_profile_commit(self) -> None:
        """A failed command write cannot commit its profile projection alone."""
        from job_correlation_evaluation_service.events.handlers import (
            handle_profile_updated,
        )

        message = MagicMock(
            pref_id="pref-id",
            pref_snapshot=_profile_snapshot(user_id="user-id", revision=2),
            metadata=MagicMock(
                event_id="88888888-8888-4888-8888-888888888888",
                version="v2",
            ),
        )
        db = create_mock_session()
        context = _make_context(db_session=db)
        wal_error = RuntimeError("WAL command write failed")

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(return_value=True),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as repository_class,
            patch(
                "job_correlation_evaluation_service.events.handlers.publish_backfill_request",
                new=AsyncMock(side_effect=wal_error),
            ) as publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as handler_settings,
        ):
            repository = AsyncMock()
            repository.upsert_profile.return_value = True
            repository_class.return_value = repository
            handler_settings.backfill.enabled = True

            with pytest.raises(RuntimeError, match="WAL command write failed"):
                await handle_profile_updated(message, context)

        repository.upsert_profile.assert_awaited_once()
        publish.assert_awaited_once()
        db.commit.assert_not_awaited()
        repository.invalidate_cache.assert_not_awaited()


class TestHandlerDeliveryBoundary:
    """Defend acknowledgement and transactional replay boundaries."""

    @pytest.mark.asyncio
    async def test_listing_handler_waits_for_terminal_publication(self) -> None:
        """The handler cannot return while atomic correlation/outbox work is pending."""
        message = MagicMock()
        message.listing = MagicMock(listing_id="listing-id", listing_url="https://example.test/job")
        message.listing_snapshot = MagicMock()
        message.metadata = MagicMock(correlation_id="correlation-id")
        context = _make_context(db_session=create_mock_session())
        matching_started = asyncio.Event()
        release_matching = asyncio.Event()

        async def complete_atomic_match(**_kwargs: object) -> int:
            matching_started.set()
            await release_matching.wait()
            return 1

        with patch("job_correlation_evaluation_service.events.handlers.JobMatcherService") as matcher_class:
            matcher = MagicMock()
            matcher.match_job_to_profiles = AsyncMock(side_effect=complete_atomic_match)
            matcher_class.return_value = matcher
            from job_correlation_evaluation_service.events.handlers import (
                handle_job_store_created,
            )

            handling = asyncio.create_task(handle_job_store_created(message, context))
            await matching_started.wait()
            assert not handling.done()
            release_matching.set()
            await handling

        matcher.match_job_to_profiles.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_rolls_back_for_kafka_policy(self) -> None:
        """Handler errors escape after rollback for retry/DLQ classification upstream."""
        from nohiki_kafka_client.handlers import DbSessionConfig
        from nohiki_kafka_client.middleware.db_session import execute_with_db_session

        session = create_mock_session()
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=session)
        manager.__aexit__ = AsyncMock(return_value=False)
        session_factory = MagicMock(return_value=manager)
        delivery_error = RuntimeError("delivery interrupted")

        async def failing_handler(_message: MagicMock, context: MessageContext) -> None:
            context.require_db_session()
            raise delivery_error

        with pytest.raises(RuntimeError, match="delivery interrupted"):
            await execute_with_db_session(
                failing_handler,
                MagicMock(),
                _make_context(),
                DbSessionConfig(auto_commit=True),
                session_factory,
            )

        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that start_event_consumer starts Kafka consumers."""
        with patch("job_correlation_evaluation_service.events.handlers.kafka_client") as mock_kafka:
            from job_correlation_evaluation_service.events.handlers import (
                start_event_consumer,
            )

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()

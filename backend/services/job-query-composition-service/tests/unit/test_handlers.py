"""Unit tests for event handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from job_query_composition_service.events.handlers import (
    _extract_frequency_tier,
    _process_affected_queries,
    handle_entitlements_changed,
    handle_profile_created,
    handle_profile_deleted,
    handle_profile_updated,
    handle_user_activity,
    handle_user_deleted,
)
from nohiki.common.v1 import CountryCode, JobBoardSource, Location, LocationType, WorkArrangement
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


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


class TestExtractFrequencyTier:
    def test_free_tier_maps_to_daily(self) -> None:
        assert _extract_frequency_tier("free") == "daily"
        assert _extract_frequency_tier("FREE") == "daily"
        assert _extract_frequency_tier("Free") == "daily"

    def test_pro_tier_maps_to_hourly(self) -> None:
        assert _extract_frequency_tier("pro") == "hourly"
        assert _extract_frequency_tier("PRO") == "hourly"

    def test_enterprise_tier_maps_to_hourly(self) -> None:
        assert _extract_frequency_tier("enterprise") == "hourly"
        assert _extract_frequency_tier("ENTERPRISE") == "hourly"


class TestProcessAffectedQueries:
    @pytest.mark.asyncio
    async def test_returns_early_without_affected_queries(self) -> None:
        db = create_mock_session()
        outbox = MagicMock()

        with patch(
            "job_query_composition_service.events.handlers.recompute_query_aggregates_batch",
            new_callable=AsyncMock,
        ) as recompute:
            await _process_affected_queries(db, outbox, set())

        recompute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recomputes_before_deleting_a_newly_empty_query(self) -> None:
        """A moved/deleted last contributor cannot leave a stale canonical query."""
        db = create_mock_session()
        outbox = MagicMock()
        query_id = uuid4()
        query = MagicMock()
        query.total_contributor_count = 0

        with (
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates_batch",
                new_callable=AsyncMock,
                return_value={query_id: query},
            ) as recompute,
            patch(
                "job_query_composition_service.events.handlers.publish_query_deleted_batch",
                new_callable=AsyncMock,
            ) as publish_deleted,
            patch(
                "job_query_composition_service.events.handlers.publish_queries_updated_batch",
                new_callable=AsyncMock,
            ) as publish_updated,
            patch(
                "job_query_composition_service.events.handlers.delete_query",
                new_callable=AsyncMock,
            ) as delete,
        ):
            await _process_affected_queries(db, outbox, {query_id})

        recompute.assert_awaited_once_with(db, {query_id})
        publish_deleted.assert_awaited_once_with(db, outbox, [query_id])
        delete.assert_awaited_once_with(db, query_id)
        publish_updated.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_partitions_recomputed_queries_into_deletes_and_updates(self) -> None:
        """Mixed contributor changes emit the canonical lifecycle event for each query."""
        db = create_mock_session()
        outbox = MagicMock()
        empty_id = uuid4()
        populated_id = uuid4()
        empty = MagicMock(total_contributor_count=0)
        populated = MagicMock(total_contributor_count=2)

        with (
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates_batch",
                new_callable=AsyncMock,
                return_value={empty_id: empty, populated_id: populated},
            ),
            patch(
                "job_query_composition_service.events.handlers.publish_query_deleted_batch",
                new_callable=AsyncMock,
            ) as publish_deleted,
            patch(
                "job_query_composition_service.events.handlers.publish_queries_updated_batch",
                new_callable=AsyncMock,
            ) as publish_updated,
            patch(
                "job_query_composition_service.events.handlers.delete_query",
                new_callable=AsyncMock,
            ) as delete,
        ):
            await _process_affected_queries(db, outbox, {empty_id, populated_id})

        publish_deleted.assert_awaited_once_with(db, outbox, [empty_id])
        delete.assert_awaited_once_with(db, empty_id)
        publish_updated.assert_awaited_once_with(db, outbox, [populated])


class TestHandleProfileCreated:
    @pytest.mark.asyncio
    async def test_skips_message_without_pref_id(self) -> None:
        mock_message = MagicMock()
        mock_message.pref_snapshot.id = ""
        context = _make_context()

        await handle_profile_created(mock_message, context)

    @pytest.mark.asyncio
    async def test_creates_contributor_and_publishes_event(self) -> None:
        pref_id = uuid4()
        user_id = uuid4()
        query_id = uuid4()

        snapshot = SearchPrefSnapshot(
            id=str(pref_id),
            user_id=str(user_id),
            pref_name="Test",
            search_keywords=["python"],
            physical_locations=[
                Location(
                    country=CountryCode.USA,
                    location_type=LocationType.PHYSICAL,
                    state_province="CA",
                    city="SF",
                )
            ],
            remote_locations=[
                Location(
                    country=CountryCode.GBR,
                    location_type=LocationType.REMOTE,
                    state_province="",
                    city="London",
                )
            ],
            work_arrangements=[WorkArrangement.REMOTE],
            scrape_sources=[JobBoardSource.LINKEDIN],
            is_active=True,
        )

        mock_message = MagicMock()
        mock_message.pref_snapshot = snapshot

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)
        mock_query = MagicMock()
        mock_query.id = query_id
        mock_query.total_contributor_count = 0

        with (
            patch(
                "job_query_composition_service.events.handlers.find_or_create_query",
                new_callable=AsyncMock,
                return_value=mock_query,
            ) as mock_find,
            patch(
                "job_query_composition_service.events.handlers.create_or_update_contributor",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates",
                new_callable=AsyncMock,
                return_value=mock_query,
            ) as mock_recompute,
            patch(
                "job_query_composition_service.events.handlers.publish_query_created",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            await handle_profile_created(mock_message, context)

            expected_locations = [loc.to_dict() for loc in snapshot.physical_locations] + [
                loc.to_dict() for loc in snapshot.remote_locations
            ]
            mock_find.assert_awaited_once_with(mock_db, ["python"], expected_locations)
            mock_create.assert_awaited_once()
            assert mock_create.call_args.args[1].locations == expected_locations
            mock_recompute.assert_awaited_once()
            mock_publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publishes_updated_event_for_existing_query(self) -> None:
        """Test that existing query triggers updated event instead of created."""
        pref_id = uuid4()
        user_id = uuid4()
        query_id = uuid4()

        snapshot = SearchPrefSnapshot(
            id=str(pref_id),
            user_id=str(user_id),
            pref_name="Test",
            search_keywords=["python"],
            physical_locations=[
                Location(
                    country=CountryCode.USA,
                    location_type=LocationType.PHYSICAL,
                    state_province="NY",
                    city="NYC",
                )
            ],
            remote_locations=[],
            work_arrangements=[WorkArrangement.REMOTE],
            scrape_sources=[JobBoardSource.LINKEDIN],
            is_active=True,
        )

        mock_message = MagicMock()
        mock_message.pref_snapshot = snapshot

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)
        mock_query = MagicMock()
        mock_query.id = query_id
        mock_query.total_contributor_count = 5

        with (
            patch(
                "job_query_composition_service.events.handlers.find_or_create_query",
                new_callable=AsyncMock,
                return_value=mock_query,
            ) as mock_find,
            patch(
                "job_query_composition_service.events.handlers.create_or_update_contributor",
                new_callable=AsyncMock,
            ),
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates",
                new_callable=AsyncMock,
                return_value=mock_query,
            ) as mock_recompute,
            patch(
                "job_query_composition_service.events.handlers.publish_query_created",
                new_callable=AsyncMock,
            ) as mock_created,
            patch(
                "job_query_composition_service.events.handlers.publish_query_updated",
                new_callable=AsyncMock,
            ) as mock_updated,
        ):
            await handle_profile_created(mock_message, context)

            expected_locations = [loc.to_dict() for loc in snapshot.physical_locations]
            mock_find.assert_awaited_once_with(mock_db, ["python"], expected_locations)
            mock_created.assert_not_awaited()
            mock_updated.assert_awaited_once()
            mock_recompute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_early_when_recompute_fails(self) -> None:
        """Test that handler returns early when recompute returns None."""
        pref_id = uuid4()
        user_id = uuid4()
        query_id = uuid4()

        snapshot = SearchPrefSnapshot(
            id=str(pref_id),
            user_id=str(user_id),
            pref_name="Test",
            search_keywords=["python"],
            physical_locations=[],
            remote_locations=[],
            work_arrangements=[],
            scrape_sources=[],
            is_active=True,
        )

        mock_message = MagicMock()
        mock_message.pref_snapshot = snapshot

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)
        mock_query = MagicMock()
        mock_query.id = query_id
        mock_query.total_contributor_count = 0

        with (
            patch(
                "job_query_composition_service.events.handlers.find_or_create_query",
                new_callable=AsyncMock,
                return_value=mock_query,
            ) as mock_find,
            patch(
                "job_query_composition_service.events.handlers.create_or_update_contributor",
                new_callable=AsyncMock,
            ),
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_recompute,
            patch(
                "job_query_composition_service.events.handlers.publish_query_created",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            await handle_profile_created(mock_message, context)

            mock_find.assert_awaited_once()
            mock_recompute.assert_awaited_once()
            mock_publish.assert_not_awaited()


class TestHandleProfileUpdated:
    @pytest.mark.asyncio
    async def test_skips_message_without_pref_id(self) -> None:
        message = MagicMock()
        message.pref_snapshot.id = ""

        await handle_profile_updated(message, _make_context())

    @pytest.mark.asyncio
    async def test_lone_recent_update_recomputes_and_publishes_immediately(self) -> None:
        """A material update is never suppressed by the removed time throttle."""
        pref_id = uuid4()
        user_id = uuid4()
        query_id = uuid4()
        snapshot = SearchPrefSnapshot(
            id=str(pref_id),
            user_id=str(user_id),
            pref_name="Test",
            search_keywords=["python", "developer"],
            physical_locations=[],
            remote_locations=[],
            work_arrangements=[WorkArrangement.REMOTE],
            scrape_sources=[JobBoardSource.LINKEDIN],
            is_active=True,
        )
        message = MagicMock(pref_snapshot=snapshot)
        db = create_mock_session()
        outbox = MagicMock()
        query = MagicMock()
        query.id = query_id
        query.total_contributor_count = 1
        query.last_recomputed_at = datetime.now(UTC)
        contributor = MagicMock()
        contributor.previous_query_id = None

        with (
            patch(
                "job_query_composition_service.events.handlers.find_or_create_query",
                new_callable=AsyncMock,
                return_value=query,
            ),
            patch(
                "job_query_composition_service.events.handlers.create_or_update_contributor",
                new_callable=AsyncMock,
                return_value=contributor,
            ),
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates",
                new_callable=AsyncMock,
                return_value=query,
            ) as recompute,
            patch(
                "job_query_composition_service.events.handlers.publish_query_updated",
                new_callable=AsyncMock,
            ) as publish_updated,
            patch(
                "job_query_composition_service.events.handlers.publish_query_created",
                new_callable=AsyncMock,
            ) as publish_created,
        ):
            await handle_profile_updated(message, _make_context(db_session=db, outbox=outbox))

        recompute.assert_awaited_once_with(db, query_id)
        publish_updated.assert_awaited_once_with(db, outbox, query)
        publish_created.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lone_contributor_move_creates_target_and_deletes_orphan(self) -> None:
        """Moving the sole preference emits one target create and removes its old query."""
        pref_id = uuid4()
        user_id = uuid4()
        old_query_id = uuid4()
        target_query_id = uuid4()
        snapshot = SearchPrefSnapshot(
            id=str(pref_id),
            user_id=str(user_id),
            pref_name="Moved",
            search_keywords=["rust"],
            physical_locations=[],
            remote_locations=[],
            work_arrangements=[WorkArrangement.REMOTE],
            scrape_sources=[JobBoardSource.LINKEDIN],
            is_active=True,
        )
        message = MagicMock(pref_snapshot=snapshot)
        db = create_mock_session()
        outbox = MagicMock()
        target = MagicMock()
        target.id = target_query_id
        target.total_contributor_count = 0
        contributor = MagicMock()
        contributor.previous_query_id = old_query_id
        old_query = MagicMock(total_contributor_count=0)

        with (
            patch(
                "job_query_composition_service.events.handlers.find_or_create_query",
                new_callable=AsyncMock,
                return_value=target,
            ),
            patch(
                "job_query_composition_service.events.handlers.create_or_update_contributor",
                new_callable=AsyncMock,
                return_value=contributor,
            ),
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates",
                new_callable=AsyncMock,
                return_value=target,
            ),
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates_batch",
                new_callable=AsyncMock,
                return_value={old_query_id: old_query},
            ),
            patch(
                "job_query_composition_service.events.handlers.publish_query_created",
                new_callable=AsyncMock,
            ) as publish_created,
            patch(
                "job_query_composition_service.events.handlers.publish_query_updated",
                new_callable=AsyncMock,
            ) as publish_updated,
            patch(
                "job_query_composition_service.events.handlers.publish_query_deleted_batch",
                new_callable=AsyncMock,
            ) as publish_deleted,
            patch(
                "job_query_composition_service.events.handlers.delete_query",
                new_callable=AsyncMock,
            ) as delete_query,
        ):
            await handle_profile_updated(message, _make_context(db_session=db, outbox=outbox))

        publish_created.assert_awaited_once_with(db, outbox, target)
        publish_updated.assert_not_awaited()
        publish_deleted.assert_awaited_once_with(db, outbox, [old_query_id])
        delete_query.assert_awaited_once_with(db, old_query_id)


class TestHandleProfileDeleted:
    @pytest.mark.asyncio
    async def test_skips_message_without_pref_id(self) -> None:
        mock_message = MagicMock()
        mock_message.pref_id = ""
        context = _make_context()

        await handle_profile_deleted(mock_message, context)

    @pytest.mark.asyncio
    async def test_deletes_query_when_last_contributor(self) -> None:
        """Test that query is deleted when last contributor is removed."""
        pref_id = uuid4()
        query_id = uuid4()
        mock_message = MagicMock()
        mock_message.pref_id = str(pref_id)

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch(
                "job_query_composition_service.events.handlers.delete_contributor",
                new_callable=AsyncMock,
                return_value=(query_id, True),
            ) as mock_delete_contrib,
            patch(
                "job_query_composition_service.events.handlers.publish_query_deleted",
                new_callable=AsyncMock,
            ) as mock_publish,
            patch(
                "job_query_composition_service.events.handlers.delete_query",
                new_callable=AsyncMock,
            ) as mock_delete_query,
        ):
            await handle_profile_deleted(mock_message, context)

            mock_delete_contrib.assert_awaited_once()
            mock_publish.assert_awaited_once()
            mock_delete_query.assert_awaited_once_with(mock_db, query_id)

    @pytest.mark.asyncio
    async def test_recomputes_query_when_not_last_contributor(self) -> None:
        """Test that query is recomputed when contributor is removed but not last."""
        pref_id = uuid4()
        query_id = uuid4()
        mock_message = MagicMock()
        mock_message.pref_id = str(pref_id)

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)
        mock_query = MagicMock()

        with (
            patch(
                "job_query_composition_service.events.handlers.delete_contributor",
                new_callable=AsyncMock,
                return_value=(query_id, False),
            ) as mock_delete_contrib,
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates",
                new_callable=AsyncMock,
                return_value=mock_query,
            ) as mock_recompute,
            patch(
                "job_query_composition_service.events.handlers.publish_query_updated",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            await handle_profile_deleted(mock_message, context)

            mock_delete_contrib.assert_awaited_once()
            mock_recompute.assert_awaited_once_with(mock_db, query_id)
            mock_publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_already_deleted_contributor(self) -> None:
        pref_id = uuid4()
        mock_message = MagicMock()
        mock_message.pref_id = str(pref_id)

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch(
            "job_query_composition_service.events.handlers.delete_contributor",
            new_callable=AsyncMock,
            return_value=(None, False),
        ) as mock_delete:
            await handle_profile_deleted(mock_message, context)

            mock_delete.assert_awaited_once()


class TestHandleEntitlementsChanged:
    @pytest.mark.asyncio
    async def test_skips_message_without_user_id(self) -> None:
        mock_message = MagicMock()
        mock_message.user_id = ""
        context = _make_context()

        await handle_entitlements_changed(mock_message, context)

    @pytest.mark.asyncio
    async def test_updates_frequency_and_recomputes_affected_queries(self) -> None:
        """Test that entitlements change updates contributor frequency and recomputes via batch."""
        user_id = uuid4()
        query_id = uuid4()
        mock_message = MagicMock()
        mock_message.user_id = str(user_id)
        mock_message.entitlement_snapshot.tier.name = "PRO"

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)
        mock_query = MagicMock()

        with (
            patch(
                "job_query_composition_service.events.handlers.update_contributor_frequency",
                new_callable=AsyncMock,
                return_value=[query_id],
            ) as mock_update,
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates_batch",
                new_callable=AsyncMock,
                return_value={query_id: mock_query},
            ) as mock_recompute_batch,
            patch(
                "job_query_composition_service.events.handlers.publish_queries_updated_batch",
                new_callable=AsyncMock,
            ) as mock_publish_batch,
        ):
            await handle_entitlements_changed(mock_message, context)

            mock_update.assert_awaited_once()
            mock_recompute_batch.assert_awaited_once()
            mock_publish_batch.assert_awaited_once()


class TestHandleUserDeleted:
    @pytest.mark.asyncio
    async def test_skips_message_without_user_id(self) -> None:
        mock_message = MagicMock()
        mock_message.user_id = ""
        context = _make_context()

        await handle_user_deleted(mock_message, context)

    @pytest.mark.asyncio
    async def test_handles_user_with_no_contributions(self) -> None:
        user_id = uuid4()
        mock_message = MagicMock()
        mock_message.user_id = str(user_id)

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch(
                "job_query_composition_service.events.handlers.delete_user_contributions",
                new_callable=AsyncMock,
                return_value=set(),
            ) as mock_delete,
            patch(
                "job_query_composition_service.events.handlers._process_affected_queries",
                new_callable=AsyncMock,
            ) as mock_process,
        ):
            await handle_user_deleted(mock_message, context)

            mock_delete.assert_awaited_once()
            mock_process.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_processes_affected_queries_when_contributions_exist(self) -> None:
        """Test that affected queries are processed when user has contributions."""
        user_id = uuid4()
        query_id = uuid4()
        mock_message = MagicMock()
        mock_message.user_id = str(user_id)

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)

        with (
            patch(
                "job_query_composition_service.events.handlers.delete_user_contributions",
                new_callable=AsyncMock,
                return_value={query_id},
            ) as mock_delete,
            patch(
                "job_query_composition_service.events.handlers._process_affected_queries",
                new_callable=AsyncMock,
            ) as mock_process,
        ):
            await handle_user_deleted(mock_message, context)

            mock_delete.assert_awaited_once()
            mock_process.assert_awaited_once()


class TestHandleUserActivity:
    @pytest.mark.asyncio
    async def test_skips_message_without_user_id(self) -> None:
        mock_message = MagicMock()
        mock_message.user_id = ""
        context = _make_context()

        await handle_user_activity(mock_message, context)

    @pytest.mark.asyncio
    async def test_reactivates_user_and_recomputes_queries(self) -> None:
        """Test that user activity reactivates user and recomputes queries via batch."""
        user_id = uuid4()
        query_id = uuid4()
        mock_message = MagicMock()
        mock_message.user_id = str(user_id)

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        context = _make_context(db_session=mock_db, outbox=mock_outbox)
        mock_query = MagicMock()

        with (
            patch(
                "job_query_composition_service.events.handlers.set_user_active",
                new_callable=AsyncMock,
                return_value=[query_id],
            ) as mock_set_active,
            patch(
                "job_query_composition_service.events.handlers.recompute_query_aggregates_batch",
                new_callable=AsyncMock,
                return_value={query_id: mock_query},
            ) as mock_recompute_batch,
            patch(
                "job_query_composition_service.events.handlers.publish_queries_updated_batch",
                new_callable=AsyncMock,
            ) as mock_publish_batch,
        ):
            await handle_user_activity(mock_message, context)

            mock_set_active.assert_awaited_once()
            mock_recompute_batch.assert_awaited_once()
            mock_publish_batch.assert_awaited_once()

"""Real database integration tests for profile event handlers.

Uses testcontainers for PostgreSQL - NO MOCKING of database operations.
Only external services (Kafka publishing) are mocked.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from job_correlation_evaluation_service.db.models import ProfileProjection
from job_correlation_evaluation_service.repositories.projection_repository import (
    ProfileProjectionRepository,
)
from nohiki.common.v1 import EntityTimestamps, EventMetadata
from nohiki.user.pref.v1 import PrefCreated, SearchPrefSnapshot
from nohiki_kafka_client import MessageContext
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _create_profile_snapshot(
    *,
    pref_id: str | None = None,
    user_id: str | None = None,
    pref_name: str = "Test Profile",
    is_active: bool = True,
    revision: int = 1,
) -> SearchPrefSnapshot:
    """Create a SearchPrefSnapshot for testing."""
    return SearchPrefSnapshot(
        id=pref_id or str(uuid4()),
        user_id=user_id or str(uuid4()),
        pref_name=pref_name,
        is_active=is_active,
        search_keywords=["python", "backend"],
        disallowed_keywords=["frontend"],
        work_arrangements=[],
        example_uploads=[],
        timestamps=EntityTimestamps(
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, revision, tzinfo=UTC),
        ),
        context_uploads=[],
    )


def _create_message_context() -> MessageContext:
    """Create a MessageContext for testing."""
    return MessageContext(
        topic="test.topic",
        partition=0,
        offset=0,
        key=None,
        headers={},
        correlation_id=str(uuid4()),
        timestamp=int(datetime.now(UTC).timestamp() * 1000),
    )


@pytest.mark.integration
class TestProfileCreatedHandlerRealDB:
    """Real database integration tests for profile created handler."""

    @pytest.mark.asyncio
    async def test_profile_created_stores_in_database(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Test that profile created handler stores profile in real PostgreSQL."""
        snapshot = _create_profile_snapshot()
        repo = ProfileProjectionRepository(async_session)
        assert snapshot.timestamps is not None
        assert snapshot.timestamps.updated_at is not None
        await repo.upsert_profile(snapshot, snapshot.timestamps.updated_at)
        await async_session.commit()

        stmt = select(ProfileProjection).where(ProfileProjection.id == snapshot.id)
        result = await async_session.execute(stmt)
        projection = result.scalar_one_or_none()

        assert projection is not None
        assert projection.profile_name == "Test Profile"
        assert projection.is_active is True
        assert str(projection.user_id) == snapshot.user_id

    @pytest.mark.asyncio
    async def test_profile_created_triggers_backfill_when_enabled(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Test that backfill is triggered when enabled."""
        snapshot = _create_profile_snapshot()
        message = PrefCreated(
            metadata=EventMetadata(
                event_id=str(uuid4()),
                timestamp=datetime.now(UTC),
                source_service="user-pref-service",
                version="v1",
            ),
            pref_id=snapshot.id,
            pref_snapshot=snapshot,
        )
        context = _create_message_context()
        context.db_session = async_session

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers.publish_backfill_request",
                new_callable=AsyncMock,
            ) as mock_publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as mock_settings,
        ):
            mock_settings.backfill.enabled = True

            from job_correlation_evaluation_service.events.handlers import (
                handle_profile_created,
            )

            await handle_profile_created(message, context)

        mock_publish.assert_awaited_once()
        assert mock_publish.await_args is not None
        published_db, request = mock_publish.await_args.args
        assert published_db is async_session
        assert request.pref_id == snapshot.id
        assert request.user_id == snapshot.user_id

        stmt = select(ProfileProjection).where(ProfileProjection.id == snapshot.id)
        result = await async_session.execute(stmt)
        projection = result.scalar_one_or_none()
        assert projection is not None


@pytest.mark.integration
class TestProfileUpdatedHandlerRealDB:
    """Real database integration tests for profile updated handler."""

    @pytest.mark.asyncio
    async def test_profile_updated_modifies_database(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Test that profile updated handler modifies profile in real PostgreSQL."""
        original = _create_profile_snapshot(pref_name="Original Name")
        repo = ProfileProjectionRepository(async_session)
        assert original.timestamps is not None
        assert original.timestamps.updated_at is not None
        await repo.upsert_profile(original, original.timestamps.updated_at)
        await async_session.commit()

        updated = _create_profile_snapshot(
            pref_id=original.id,
            user_id=original.user_id,
            pref_name="Updated Name",
            revision=3,
        )
        assert updated.timestamps is not None
        assert updated.timestamps.updated_at is not None
        await repo.upsert_profile(updated, updated.timestamps.updated_at)
        await async_session.commit()

        stale = _create_profile_snapshot(
            pref_id=original.id,
            user_id=original.user_id,
            pref_name="Stale Name",
            revision=2,
        )
        assert stale.timestamps is not None
        assert stale.timestamps.updated_at is not None
        changed = await repo.upsert_profile(stale, stale.timestamps.updated_at)
        assert changed is False
        await async_session.commit()

        stmt = select(ProfileProjection).where(ProfileProjection.id == original.id)
        result = await async_session.execute(stmt)
        projection = result.scalar_one_or_none()

        assert projection is not None
        assert projection.profile_name == "Updated Name"

    @pytest.mark.asyncio
    async def test_equal_snapshot_and_stale_tombstone_cannot_replace_current_revision(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Equal snapshots and older deletes cannot regress a live projection."""
        _ = setup_database_schema
        current = _create_profile_snapshot(pref_name="Current", revision=3)
        repo = ProfileProjectionRepository(async_session)
        assert current.timestamps is not None
        assert current.timestamps.updated_at is not None
        assert await repo.upsert_profile(current, current.timestamps.updated_at) is True

        duplicate_revision = _create_profile_snapshot(
            pref_id=current.id,
            user_id=current.user_id,
            pref_name="Conflicting equal revision",
            revision=3,
        )
        assert duplicate_revision.timestamps is not None
        assert duplicate_revision.timestamps.updated_at is not None
        assert (
            await repo.upsert_profile(
                duplicate_revision,
                duplicate_revision.timestamps.updated_at,
            )
            is False
        )
        assert (
            await repo.tombstone_profile(
                UUID(current.id),
                UUID(current.user_id),
                datetime(2026, 1, 2, tzinfo=UTC),
            )
            is False
        )

        visible = await repo.get_profile(UUID(current.id))
        assert visible is not None
        assert visible.pref_name == "Current"


@pytest.mark.integration
class TestProfileDeletedHandlerRealDB:
    """Real database tests for ordered profile tombstones."""

    @pytest.mark.asyncio
    async def test_tombstone_blocks_resurrection_until_revision_advances(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """An equal-revision delete wins; only a later lifecycle can recreate."""
        snapshot = _create_profile_snapshot(pref_name="Original", revision=1)
        repo = ProfileProjectionRepository(async_session)
        assert snapshot.timestamps is not None
        assert snapshot.timestamps.updated_at is not None
        assert await repo.upsert_profile(snapshot, snapshot.timestamps.updated_at) is True

        current = _create_profile_snapshot(
            pref_id=snapshot.id,
            user_id=snapshot.user_id,
            pref_name="Current update",
            revision=3,
        )
        assert current.timestamps is not None
        assert current.timestamps.updated_at is not None
        assert await repo.upsert_profile(current, current.timestamps.updated_at) is True

        deleted = await repo.tombstone_profile(
            UUID(snapshot.id),
            UUID(snapshot.user_id),
            datetime(2026, 1, 3, tzinfo=UTC),
        )
        assert deleted is True

        delayed = _create_profile_snapshot(
            pref_id=snapshot.id,
            user_id=snapshot.user_id,
            pref_name="Equal-revision delayed snapshot",
            revision=3,
        )
        assert delayed.timestamps is not None
        assert delayed.timestamps.updated_at is not None
        assert await repo.upsert_profile(delayed, delayed.timestamps.updated_at) is False
        assert await repo.get_profile(UUID(snapshot.id)) is None

        recreated = _create_profile_snapshot(
            pref_id=snapshot.id,
            user_id=snapshot.user_id,
            pref_name="Recreated",
            revision=4,
        )
        assert recreated.timestamps is not None
        assert recreated.timestamps.updated_at is not None
        assert await repo.upsert_profile(recreated, recreated.timestamps.updated_at) is True
        await async_session.commit()

        visible = await repo.get_profile(UUID(snapshot.id))
        assert visible is not None
        assert visible.pref_name == "Recreated"

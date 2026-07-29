"""Unit tests for projection repositories."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from job_correlation_evaluation_service.repositories.projection_repository import (
    ACTIVE_PROFILES_CACHE_KEY,
    ProfileProjectionRepository,
)
from nohiki.user.pref.v1 import SearchPrefSnapshot


class TestProfileProjectionRepository:
    """Tests for ProfileProjectionRepository."""


class TestGetActiveProfiles:
    """Tests for get_active_profiles method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def mock_cache(self) -> AsyncMock:
        """Create a cache miss without opening a Redis connection."""
        cache = AsyncMock()
        cache.get.return_value = None
        return cache

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create cache settings."""
        settings = MagicMock()
        settings.caching.active_profiles_ttl = 300
        return settings

    @pytest.fixture
    def repository(
        self, mock_session: AsyncMock, mock_cache: AsyncMock, mock_settings: MagicMock
    ) -> ProfileProjectionRepository:
        """Create repository with database and cache dependencies isolated."""
        return ProfileProjectionRepository(session=mock_session, cache=mock_cache, settings=mock_settings)

    @pytest.mark.asyncio
    async def test_get_active_profiles_returns_list(
        self,
        repository: ProfileProjectionRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_active_profiles returns list of SearchPrefSnapshot."""
        mock_projection = MagicMock()
        mock_projection.id = uuid4()
        mock_projection.user_id = uuid4()
        mock_projection.profile_name = "Test Profile"
        mock_projection.is_active = True
        mock_projection.snapshot_data = {
            "id": str(mock_projection.id),
            "user_id": str(mock_projection.user_id),
            "pref_name": "Test Profile",
            "is_active": True,
            "search_keywords": ["python"],
        }

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_projection]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.get_active_profiles()

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], SearchPrefSnapshot)

    @pytest.mark.asyncio
    async def test_get_active_profiles_empty(
        self,
        repository: ProfileProjectionRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_active_profiles returns empty list when no active profiles."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository.get_active_profiles()

        assert result == []


class TestUpsertProfile:
    """Tests for upsert_profile method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> ProfileProjectionRepository:
        """Create repository with mock session."""
        return ProfileProjectionRepository(session=mock_session)

    @pytest.fixture
    def sample_profile(self) -> SearchPrefSnapshot:
        """Create sample profile."""
        return SearchPrefSnapshot(
            id=str(uuid4()),
            user_id=str(uuid4()),
            pref_name="Test Profile",
            is_active=True,
            search_keywords=["python", "backend"],
        )

    @pytest.mark.asyncio
    async def test_upsert_profile_executes_insert(
        self,
        repository: ProfileProjectionRepository,
        mock_session: AsyncMock,
        sample_profile: SearchPrefSnapshot,
    ) -> None:
        """Test upsert_profile executes database upsert statement."""
        revision = datetime(2026, 1, 2, tzinfo=UTC)
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_profile.id
        mock_session.execute.return_value = result
        changed = await repository.upsert_profile(sample_profile, revision)

        # Repository executes statement; commit is handled by session context
        mock_session.execute.assert_called_once()
        assert changed is True
        assert mock_session.execute.await_args is not None
        assert "excluded.source_revision >" in str(mock_session.execute.await_args.args[0])

    @pytest.mark.asyncio
    async def test_upsert_profile_with_inactive_profile(
        self,
        repository: ProfileProjectionRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test upsert_profile handles inactive profiles."""
        inactive_profile = SearchPrefSnapshot(
            id=str(uuid4()),
            user_id=str(uuid4()),
            pref_name="Inactive Profile",
            is_active=False,
        )

        result = MagicMock()
        result.scalar_one_or_none.return_value = inactive_profile.id
        mock_session.execute.return_value = result
        changed = await repository.upsert_profile(
            inactive_profile,
            datetime(2026, 1, 2, tzinfo=UTC),
        )

        # Repository executes statement; commit is handled by session context
        mock_session.execute.assert_called_once()
        assert changed is True

    @pytest.mark.asyncio
    async def test_duplicate_or_older_revision_reports_no_projection_change(
        self,
        repository: ProfileProjectionRepository,
        mock_session: AsyncMock,
        sample_profile: SearchPrefSnapshot,
    ) -> None:
        """PostgreSQL's revision guard rejects a non-advancing CDC snapshot."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result

        changed = await repository.upsert_profile(
            sample_profile,
            datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert changed is False
        assert mock_session.execute.await_args is not None
        assert "excluded.source_revision >" in str(mock_session.execute.await_args.args[0])


class TestTombstoneProfile:
    """Tests for durable ordered deletion tombstones."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> ProfileProjectionRepository:
        """Create repository with mocks."""
        return ProfileProjectionRepository(session=mock_session)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("changed", [False, True])
    async def test_tombstone_accepts_equal_or_newer_revision(
        self,
        repository: ProfileProjectionRepository,
        mock_session: AsyncMock,
        *,
        changed: bool,
    ) -> None:
        """Equal deletion wins its race; only an older deletion is rejected."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = uuid4() if changed else None
        mock_session.execute.return_value = result

        applied = await repository.tombstone_profile(
            uuid4(),
            uuid4(),
            datetime(2026, 1, 3, tzinfo=UTC),
        )

        assert applied is changed
        assert mock_session.execute.await_args is not None
        statement = str(mock_session.execute.await_args.args[0])
        assert "excluded.source_revision >=" in statement

    @pytest.mark.asyncio
    async def test_get_profile_excludes_tombstones(
        self,
        repository: ProfileProjectionRepository,
        mock_session: AsyncMock,
    ) -> None:
        """A deleted profile cannot be reconstructed for a delayed callback."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = result

        profile = await repository.get_profile(uuid4())

        assert profile is None
        assert mock_session.execute.await_args is not None
        statement = str(mock_session.execute.await_args.args[0])
        assert "profile_projections.is_active" in statement


class TestCacheAsidePattern:
    """Tests for cache-aside pattern implementation."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def mock_cache(self) -> AsyncMock:
        """Create mock Redis cache."""
        return AsyncMock()

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.caching.active_profiles_ttl = 300
        return settings

    @pytest.fixture
    def repository_with_cache(
        self, mock_session: AsyncMock, mock_cache: AsyncMock, mock_settings: MagicMock
    ) -> ProfileProjectionRepository:
        """Create repository with mocks."""
        return ProfileProjectionRepository(session=mock_session, cache=mock_cache, settings=mock_settings)

    @pytest.mark.asyncio
    async def test_get_active_profiles_cache_hit(
        self,
        repository_with_cache: ProfileProjectionRepository,
        mock_cache: AsyncMock,
    ) -> None:
        """Test get_active_profiles returns cached data on cache hit."""
        cached_data = [{"id": "profile-1", "user_id": "user-1", "pref_name": "Test"}]
        mock_cache.get.return_value = json.dumps(cached_data)

        result = await repository_with_cache.get_active_profiles()

        assert len(result) == 1
        mock_cache.get.assert_awaited_once_with(ACTIVE_PROFILES_CACHE_KEY)

    @pytest.mark.asyncio
    async def test_cached_empty_list_is_a_hit(
        self,
        repository_with_cache: ProfileProjectionRepository,
        mock_session: AsyncMock,
        mock_cache: AsyncMock,
    ) -> None:
        """A cached empty active-profile set must not fall through to PostgreSQL."""
        mock_cache.get.return_value = "[]"

        result = await repository_with_cache.get_active_profiles()

        assert result == []
        mock_session.execute.assert_not_awaited()
        mock_cache.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_active_profiles_cache_miss_queries_db(
        self,
        repository_with_cache: ProfileProjectionRepository,
        mock_session: AsyncMock,
        mock_cache: AsyncMock,
    ) -> None:
        """Test get_active_profiles queries DB on cache miss."""
        mock_cache.get.return_value = None

        mock_projection = MagicMock()
        mock_projection.snapshot_data = {
            "id": str(uuid4()),
            "user_id": str(uuid4()),
            "pref_name": "Test",
        }
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_projection]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository_with_cache.get_active_profiles()

        assert len(result) == 1
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_active_profiles_populates_cache_after_db_query(
        self,
        repository_with_cache: ProfileProjectionRepository,
        mock_session: AsyncMock,
        mock_cache: AsyncMock,
    ) -> None:
        """Test cache is populated after DB query."""
        mock_cache.get.return_value = None

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        await repository_with_cache.get_active_profiles()

        mock_cache.set.assert_awaited_once()
        call_kwargs = mock_cache.set.call_args.kwargs
        assert call_kwargs["ttl"] == 300

    @pytest.mark.asyncio
    async def test_invalidate_cache_deletes_key(
        self, repository_with_cache: ProfileProjectionRepository, mock_cache: AsyncMock
    ) -> None:
        """Test invalidate_cache deletes the cache key."""
        await repository_with_cache.invalidate_cache()

        mock_cache.delete.assert_awaited_once_with(ACTIVE_PROFILES_CACHE_KEY)

    @pytest.mark.asyncio
    async def test_cache_read_failure_falls_back_to_db(
        self,
        repository_with_cache: ProfileProjectionRepository,
        mock_session: AsyncMock,
        mock_cache: AsyncMock,
    ) -> None:
        """Test graceful fallback to DB when cache read fails."""
        mock_cache.get.side_effect = OSError("Connection refused")

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository_with_cache.get_active_profiles()

        assert result == []
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_write_failure_does_not_raise(
        self,
        repository_with_cache: ProfileProjectionRepository,
        mock_session: AsyncMock,
        mock_cache: AsyncMock,
    ) -> None:
        """Test cache write failure doesn't raise exception."""
        mock_cache.get.return_value = None
        mock_cache.set.side_effect = OSError("Connection refused")

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository_with_cache.get_active_profiles()

        assert result == []

    @pytest.mark.asyncio
    async def test_invalidate_cache_failure_does_not_raise(
        self, repository_with_cache: ProfileProjectionRepository, mock_cache: AsyncMock
    ) -> None:
        """Test cache invalidation failure doesn't raise exception."""
        mock_cache.delete.side_effect = OSError("Connection refused")

        await repository_with_cache.invalidate_cache()

    @pytest.mark.asyncio
    async def test_corrupted_cache_data_falls_back_to_db(
        self,
        repository_with_cache: ProfileProjectionRepository,
        mock_session: AsyncMock,
        mock_cache: AsyncMock,
    ) -> None:
        """Test graceful fallback when cache data is corrupted."""
        mock_cache.get.return_value = "invalid json {"

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        result = await repository_with_cache.get_active_profiles()

        assert result == []
        mock_session.execute.assert_awaited_once()

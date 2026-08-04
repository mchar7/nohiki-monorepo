"""REAL database integration tests for repository operations.

Uses testcontainers to spin up actual PostgreSQL instances.
NO MOCKING of database operations - tests real SQL execution.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from job_correlation_evaluation_service.db.models import Correlation, ProfileProjection
from job_correlation_evaluation_service.repositories.correlation_repository import (
    CorrelationNotFoundError,
    CorrelationRepository,
)
from job_correlation_evaluation_service.repositories.match_record_repository import (
    MatchRecordRepository,
)
from job_correlation_evaluation_service.repositories.projection_repository import (
    ProfileProjectionRepository,
)
from job_correlation_evaluation_service.services.match_types import JobMatchResult
from nohiki.common.v1 import CorrelationStatus, UserFeedback
from nohiki.user.pref.v1 import SearchPrefSnapshot
from pytest_unused_fixtures import ignore_unused_fixture
from sqlalchemy import select

if TYPE_CHECKING:
    from nohiki_redis_utils import RedisCache
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.requires_docker


PROFILE_REVISION = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.integration
class TestMatchRecordRepositoryRealDB:
    """Real database integration tests for MatchRecordRepository."""

    @pytest.fixture
    @ignore_unused_fixture
    def sample_match_result(self) -> JobMatchResult:
        """Create a sample match result."""
        return JobMatchResult(
            pref_id=str(uuid.uuid4()),
            listing_id=str(uuid.uuid4()),
            listing_url="https://example.com/job/123",
            score=85,
            breakdown={
                "ml_score": 85,
                "ml_confidence": 0.92,
                "scoring_method": "ml_pipeline",
            },
            feature_schema_version="v5.0.0",
            role_relevance_raw=0.0,
            ranking_index=0.0,
            factors=(),
            feature_vector=(0.7, 0.8, 0.9),
        )

    @pytest.mark.asyncio
    async def test_record_match_persists_to_database(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
        sample_match_result: JobMatchResult,
    ) -> None:
        """Test that record_match persists correlation to real PostgreSQL."""
        repo = MatchRecordRepository(async_session)
        user_id = str(uuid.uuid4())

        inserted = await repo.record_match(sample_match_result, user_id)

        assert inserted is True

        stmt = select(Correlation).where(
            Correlation.pref_id == uuid.UUID(sample_match_result.pref_id),
            Correlation.listing_id == uuid.UUID(sample_match_result.listing_id),
        )
        result = await async_session.execute(stmt)
        correlation = result.scalar_one_or_none()

        assert correlation is not None
        assert correlation.correlation_score == 85
        assert correlation.user_id == uuid.UUID(user_id)
        assert correlation.correlation_status == CorrelationStatus.EVALUATED
        assert correlation.feature_vector == [0.7, 0.8, 0.9]

    @pytest.mark.asyncio
    async def test_exists_queries_real_database(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
        sample_match_result: JobMatchResult,
    ) -> None:
        """Test exists() queries real PostgreSQL."""
        repo = MatchRecordRepository(async_session)
        user_id = str(uuid.uuid4())

        exists_before = await repo.exists(
            sample_match_result.pref_id,
            sample_match_result.listing_id,
        )
        assert exists_before is False

        await repo.record_match(sample_match_result, user_id)
        await async_session.commit()

        exists_after = await repo.exists(
            sample_match_result.pref_id,
            sample_match_result.listing_id,
        )
        assert exists_after is True

    @pytest.mark.asyncio
    async def test_get_existing_listing_ids_batch_query(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Test batch query for existing listing IDs."""
        repo = MatchRecordRepository(async_session)
        pref_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        listing_ids = [str(uuid.uuid4()) for _ in range(5)]

        for i, listing_id in enumerate(listing_ids[:3]):
            match_result = JobMatchResult(
                pref_id=pref_id,
                listing_id=listing_id,
                listing_url=f"https://example.com/job/{i}",
                score=80 + i,
                breakdown={"ml_score": 80 + i},
                feature_schema_version="v5.0.0",
                role_relevance_raw=0.0,
                ranking_index=0.0,
                factors=(),
                feature_vector=(0.7, 0.8, 0.9),
            )
            await repo.record_match(match_result, user_id)

        await async_session.commit()

        existing = await repo.get_existing_listing_ids(pref_id, listing_ids)

        assert len(existing) == 3
        for lid in listing_ids[:3]:
            assert lid in existing


@pytest.mark.integration
class TestCorrelationRepositoryRealDB:
    """Real database integration tests for CorrelationRepository."""

    @pytest_asyncio.fixture
    @ignore_unused_fixture
    async def sample_correlation(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> Correlation:
        """Create and persist a sample correlation."""
        correlation = Correlation(
            id=uuid.uuid4(),
            pref_id=uuid.uuid4(),
            listing_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            listing_url="https://example.com/job/test",
            correlation_score=75,
            correlation_reasoning={"test": "data"},
            correlation_status=CorrelationStatus.PENDING,
            feature_schema_version="v5.0.0",
        )
        async_session.add(correlation)
        await async_session.commit()
        await async_session.refresh(correlation)
        return correlation

    @pytest.mark.asyncio
    async def test_get_by_id_retrieves_from_database(
        self,
        async_session: AsyncSession,
        sample_correlation: Correlation,
    ) -> None:
        """Test get_by_id retrieves correlation from real PostgreSQL."""
        repo = CorrelationRepository(async_session)

        result = await repo.get_by_id(sample_correlation.id)

        assert result is not None
        assert result.id == sample_correlation.id
        assert result.correlation_score == 75

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_for_missing(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Test get_by_id returns None for non-existent ID."""
        repo = CorrelationRepository(async_session)
        missing_id = uuid.uuid4()

        result = await repo.get_by_id(missing_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_update_modifies_database(
        self,
        async_session: AsyncSession,
        sample_correlation: Correlation,
    ) -> None:
        """Test update modifies correlation in real PostgreSQL."""
        repo = CorrelationRepository(async_session)

        updated = await repo.update(
            sample_correlation.id,
            is_viewed=True,
            user_feedback=UserFeedback.POSITIVE,
        )

        assert updated.is_viewed is True
        assert updated.user_feedback == UserFeedback.POSITIVE

        stmt = select(Correlation).where(Correlation.id == sample_correlation.id)
        result = await async_session.execute(stmt)
        db_correlation = result.scalar_one()
        assert db_correlation.is_viewed is True
        assert db_correlation.user_feedback == UserFeedback.POSITIVE

    @pytest.mark.asyncio
    async def test_update_raises_for_missing_correlation(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Test update raises CorrelationNotFoundError for missing ID."""
        repo = CorrelationRepository(async_session)
        missing_id = uuid.uuid4()

        with pytest.raises(CorrelationNotFoundError):
            await repo.update(missing_id, is_viewed=True)

    @pytest.mark.asyncio
    async def test_get_feedback_stats_aggregates_correctly(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Test feedback stats aggregation with real data."""
        repo = CorrelationRepository(async_session)
        user_id = uuid.uuid4()

        feedback_types = [
            (True, False, False, UserFeedback.POSITIVE),
            (True, True, False, None),
            (True, False, False, None),
            (False, False, True, None),
            (True, False, False, None),
        ]

        for i, (viewed, applied, dismissed, feedback) in enumerate(feedback_types):
            correlation = Correlation(
                id=uuid.uuid4(),
                pref_id=uuid.uuid4(),
                listing_id=uuid.uuid4(),
                user_id=user_id,
                listing_url=f"https://example.com/job/{i}",
                correlation_score=70 + i,
                correlation_status=CorrelationStatus.EVALUATED,
                is_viewed=viewed,
                is_applied=applied,
                is_dismissed=dismissed,
                user_feedback=feedback,
                feature_schema_version="v5.0.0",
            )
            async_session.add(correlation)

        await async_session.commit()

        stats = await repo.get_feedback_stats()

        feedback_by_type = stats["feedback_by_type"]
        assert isinstance(feedback_by_type, dict)
        assert feedback_by_type["viewed"] == 4
        assert feedback_by_type["applied"] == 1
        assert feedback_by_type["dismissed"] == 1
        assert feedback_by_type["positive"] == 1


@pytest.mark.integration
class TestProfileProjectionRepositoryRealDB:
    """Real database integration tests for ProfileProjectionRepository."""

    @pytest.fixture
    @ignore_unused_fixture
    def sample_profile(self) -> SearchPrefSnapshot:
        """Create a sample profile snapshot."""
        return SearchPrefSnapshot(
            id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            pref_name="Test Profile",
            is_active=True,
            search_keywords=["python", "backend"],
        )

    @pytest.mark.asyncio
    async def test_upsert_persists_to_database(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
        sample_profile: SearchPrefSnapshot,
    ) -> None:
        """Test upsert persists profile to real PostgreSQL."""
        repo = ProfileProjectionRepository(async_session)

        await repo.upsert_profile(sample_profile, PROFILE_REVISION)
        await async_session.commit()

        stmt = select(ProfileProjection).where(ProfileProjection.id == uuid.UUID(sample_profile.id))
        result = await async_session.execute(stmt)
        projection = result.scalar_one_or_none()

        assert projection is not None
        assert projection.profile_name == "Test Profile"
        assert projection.is_active is True

    @pytest.mark.asyncio
    async def test_get_profile_retrieves_from_database(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
        sample_profile: SearchPrefSnapshot,
    ) -> None:
        """Test get_profile retrieves from real PostgreSQL."""
        repo = ProfileProjectionRepository(async_session)

        await repo.upsert_profile(sample_profile, PROFILE_REVISION)
        await async_session.commit()

        result = await repo.get_profile(uuid.UUID(sample_profile.id))

        assert result is not None
        assert result.pref_name == "Test Profile"

    @pytest.mark.asyncio
    async def test_delete_hides_durable_tombstone(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
        sample_profile: SearchPrefSnapshot,
    ) -> None:
        """Deletion remains ordered while disappearing from profile reads."""
        repo = ProfileProjectionRepository(async_session)

        await repo.upsert_profile(sample_profile, PROFILE_REVISION)
        await async_session.commit()

        changed = await repo.tombstone_profile(
            uuid.UUID(sample_profile.id),
            uuid.UUID(sample_profile.user_id),
            datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert changed is True
        await async_session.commit()

        assert await repo.get_profile(uuid.UUID(sample_profile.id)) is None
        stmt = select(ProfileProjection).where(ProfileProjection.id == uuid.UUID(sample_profile.id))
        result = await async_session.execute(stmt)
        tombstone = result.scalar_one_or_none()
        assert tombstone is not None
        assert tombstone.is_active is False

    @pytest.mark.asyncio
    async def test_get_active_profiles_filters_correctly(
        self,
        async_session: AsyncSession,
        redis_cache: RedisCache,
        setup_database_schema: None,
    ) -> None:
        """Test get_active_profiles filters by is_active."""
        repo = ProfileProjectionRepository(async_session, cache=redis_cache)

        profiles = [
            SearchPrefSnapshot(
                id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
                pref_name=f"Profile {i}",
                is_active=i < 3,
                search_keywords=["test"],
            )
            for i in range(5)
        ]

        for profile in profiles:
            await repo.upsert_profile(profile, PROFILE_REVISION)
        await async_session.commit()

        active_profiles = await repo.get_active_profiles()

        assert len(active_profiles) == 3
        for profile in active_profiles:
            assert profile.is_active is True

    @pytest.mark.asyncio
    async def test_cache_invalidation_with_redis(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
        redis_cache: RedisCache,
        sample_profile: SearchPrefSnapshot,
    ) -> None:
        """Test that cache invalidation works with real Redis."""
        repo = ProfileProjectionRepository(async_session, cache=redis_cache)

        await repo.upsert_profile(sample_profile, PROFILE_REVISION)
        await async_session.commit()

        _ = await repo.get_active_profiles()

        await repo.invalidate_cache()

        updated_profile = SearchPrefSnapshot(
            id=sample_profile.id,
            user_id=sample_profile.user_id,
            pref_name="Updated Profile",
            is_active=True,
            search_keywords=["go", "rust"],
        )
        await repo.upsert_profile(
            updated_profile,
            datetime(2026, 1, 2, tzinfo=UTC),
        )
        await async_session.commit()

        profiles = await repo.get_active_profiles()

        matching = [p for p in profiles if p.id == sample_profile.id]
        assert len(matching) == 1
        assert matching[0].pref_name == "Updated Profile"

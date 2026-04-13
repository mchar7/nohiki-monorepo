"""Unit tests for services/matcher_service.py module."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki_db_utils.testing import create_mock_session


class TestJobMatchResult:
    """Tests for JobMatchResult dataclass."""

    def test_creates_job_match_result(self) -> None:
        """Test that JobMatchResult can be created."""
        from job_correlation_evaluation_service.services.match_types import (
            JobMatchResult,
        )

        result = JobMatchResult(
            pref_id="pref-123",
            listing_id="listing-456",
            listing_url="https://example.com/job",
            score=85,
            breakdown={"keyword_match": 0.8},
            feature_schema_version="v5.0.0",
            feature_vector=(0.5, 0.6, 0.7),
            role_relevance_raw=0.0,
            ranking_index=0.0,
            factors=(),
        )

        assert result.pref_id == "pref-123"
        assert result.listing_id == "listing-456"
        assert result.score == 85
        assert result.correlation_id is not None


class TestMatchContext:
    """Tests for MatchContext dataclass."""

    def test_creates_match_context(self) -> None:
        """Test that MatchContext can be created."""
        from job_correlation_evaluation_service.services.match_types import (
            MatchContext,
        )

        mock_job = MagicMock()
        mock_profile = MagicMock()

        context = MatchContext(
            listing_id="listing-123",
            listing_url="https://example.com/job",
            job=mock_job,
            profile=mock_profile,
            correlation_id="corr-456",
        )

        assert context.listing_id == "listing-123"
        assert context.correlation_id == "corr-456"


class TestBuildListingNotificationSnapshot:
    """Tests for _build_listing_notification_snapshot helper."""

    def test_builds_snapshot_from_job(self) -> None:
        """Test building snapshot using helper function."""
        from job_correlation_evaluation_service.events.publishers import (
            _build_listing_notification_snapshot,
        )

        mock_job = MagicMock()
        mock_job.id = uuid4()
        mock_job.listing_url = "https://example.com/job"
        mock_job.title = "Developer"
        mock_job.company_name = "Company"
        mock_job.location = None
        mock_job.posted_at = None

        snapshot = _build_listing_notification_snapshot(mock_job)

        assert snapshot.title == "Developer"

    def test_builds_snapshot_with_location(self) -> None:
        """Test building snapshot with location data."""
        from job_correlation_evaluation_service.events.publishers import (
            _build_listing_notification_snapshot,
        )

        mock_job = MagicMock()
        mock_job.id = uuid4()
        mock_job.listing_url = "https://example.com/job"
        mock_job.title = "Software Engineer"
        mock_job.company_name = "Tech Corp"
        mock_job.location = MagicMock()
        mock_job.location.city = "San Francisco"
        mock_job.location.state_province = "CA"
        mock_job.posted_at = None

        snapshot = _build_listing_notification_snapshot(mock_job)

        assert snapshot.title == "Software Engineer"
        assert snapshot.location is mock_job.location
        assert snapshot.location.city == "San Francisco"


class TestJobMatcherServiceInit:
    """Tests for JobMatcherService initialization."""

    def test_initializes_with_settings(self) -> None:
        """Test that service initializes with settings."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        service = JobMatcherService()

        assert service._ml_service is None

    def test_initializes_with_ml_service(self) -> None:
        """Test that service initializes with ML service."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_ml_service = MagicMock()
        service = JobMatcherService(ml_scoring_service=mock_ml_service)

        assert service._ml_service is mock_ml_service


class TestJobMatcherServiceMatchJobToProfiles:
    """Tests for match_job_to_profiles method."""

    @pytest.mark.asyncio
    async def test_raises_error_for_empty_correlation_id(self) -> None:
        """Test that empty correlation_id raises ValueError."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        service = JobMatcherService()
        mock_db = create_mock_session()
        mock_job = MagicMock()

        with pytest.raises(ValueError, match="correlation_id cannot be empty"):
            await service.match_job_to_profiles(mock_db, mock_job, "")

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_active_profiles(self) -> None:
        """Test that method returns 0 when no active profiles."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_repo = MagicMock()
        mock_repo.get_active_profiles = AsyncMock(return_value=[])

        with patch(
            "job_correlation_evaluation_service.services.matcher_service.ProfileProjectionRepository"
        ) as mock_repo_class:
            mock_repo_class.return_value = mock_repo

            service = JobMatcherService()
            mock_db = create_mock_session()
            mock_job = MagicMock()
            mock_job.id = uuid4()
            mock_job.listing_url = "https://example.com/job"

            result = await service.match_job_to_profiles(mock_db, mock_job, "corr-123")

            assert result == 0
            mock_repo.get_active_profiles.assert_awaited_once()


class TestJobMatcherServiceGetActionableMatches:
    """Tests for get_actionable_matches method."""

    @pytest.mark.asyncio
    async def test_delegates_to_repository(self) -> None:
        """Test that get_actionable_matches delegates to repository."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_matches = [MagicMock(), MagicMock()]
        mock_repo = MagicMock()
        mock_repo.get_actionable_matches = AsyncMock(return_value=mock_matches)

        with patch(
            "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository"
        ) as mock_repo_class:
            mock_repo_class.return_value = mock_repo

            service = JobMatcherService()
            mock_db = create_mock_session()

            result = await service.get_actionable_matches(mock_db, str(uuid4()))

            assert len(result) == 2
            mock_repo.get_actionable_matches.assert_awaited_once()


class TestJobMatcherServiceDismissMatches:
    """Tests for dismiss_matches_for_deleted_job method."""

    @pytest.mark.asyncio
    async def test_delegates_to_repository(self) -> None:
        """Test that dismiss_matches_for_deleted_job delegates to repository."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_repo = MagicMock()
        mock_repo.dismiss_for_deleted_listing = AsyncMock(return_value=5)

        with patch(
            "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository"
        ) as mock_repo_class:
            mock_repo_class.return_value = mock_repo

            service = JobMatcherService()
            mock_db = create_mock_session()

            result = await service.dismiss_matches_for_deleted_job(mock_db, uuid4())

            assert result == 5
            mock_repo.dismiss_for_deleted_listing.assert_awaited_once()


class TestJobMatcherServiceMatchJobWithActiveProfiles:
    """Tests for match_job_to_profiles with active profiles."""

    @pytest.mark.asyncio
    async def test_matches_multiple_profiles(self) -> None:
        """Test matching a job against multiple active profiles."""
        from job_correlation_evaluation_service.services.match_types import (
            JobMatchResult,
        )
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_db = create_mock_session()
        mock_job = MagicMock()
        mock_job.id = uuid4()
        mock_job.listing_url = "https://example.com/job"

        profile1 = MagicMock()
        profile1.id = str(uuid4())
        profile1.user_id = str(uuid4())
        profile2 = MagicMock()
        profile2.id = str(uuid4())
        profile2.user_id = str(uuid4())

        mock_profile_repo = MagicMock()
        mock_profile_repo.get_active_profiles = AsyncMock(return_value=[profile1, profile2])

        mock_match_repo = MagicMock()
        mock_match_repo.get_existing_pref_ids = AsyncMock(return_value=set())
        mock_match_repo.record_match_no_commit = AsyncMock()

        mock_result = JobMatchResult(
            pref_id=profile1.id,
            listing_id=str(mock_job.id),
            listing_url="https://example.com/job",
            score=75,
            breakdown={},
            feature_schema_version="v5.0.0",
            feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
            role_relevance_raw=0.0,
            ranking_index=0.0,
            factors=(),
        )
        mock_pipeline = MagicMock()
        mock_pipeline.execute = MagicMock(return_value=mock_result)

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.ProfileProjectionRepository"
            ) as mock_profile_repo_class,
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository"
            ) as mock_match_repo_class,
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated"
            ) as mock_publish,
        ):
            mock_profile_repo_class.return_value = mock_profile_repo
            mock_match_repo_class.return_value = mock_match_repo
            mock_publish.return_value = None

            service = JobMatcherService()
            # Mock ML service properly
            from job_correlation_evaluation_service.services.scoring_service import (
                MLScoringResult,
            )

            mock_ml_result = MLScoringResult(
                score=75,
                is_disqualified=False,
                disqualification_reason=None,
                feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
            )
            service._ml_service = MagicMock()
            service._ml_service.is_initialized = True
            service._ml_service.extract_query_encoding_from_snapshot = MagicMock(return_value=MagicMock())
            service._ml_service.score_with_inline_embeddings = MagicMock(return_value=mock_ml_result)

            result = await service.match_job_to_profiles(mock_db, mock_job, "corr-123")

            assert result == 2
            assert mock_publish.call_count == 2


class TestJobMatcherServiceMLScoring:
    """Tests for ML scoring methods in JobMatcherService."""

    def test_is_ml_service_ready_returns_false_when_none(self) -> None:
        """Test _is_ml_service_ready returns False when ML service is None."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        service = JobMatcherService()
        service._ml_service = None

        assert service._is_ml_service_ready() is False

    def test_is_ml_service_ready_returns_false_when_not_initialized(self) -> None:
        """Test _is_ml_service_ready returns False when not initialized."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_ml = MagicMock()
        mock_ml.is_initialized = False

        service = JobMatcherService()
        service._ml_service = mock_ml

        assert service._is_ml_service_ready() is False

    def test_is_ml_service_ready_returns_true_when_initialized(self) -> None:
        """Test _is_ml_service_ready returns True when initialized."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_ml = MagicMock()
        mock_ml.is_initialized = True

        service = JobMatcherService()
        service._ml_service = mock_ml

        assert service._is_ml_service_ready() is True

    def test_convert_ml_results_creates_job_match_results(self) -> None:
        """Test _convert_ml_results creates JobMatchResult objects."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        service = JobMatcherService()

        listing_id = str(uuid4())
        mock_listing = MagicMock()
        mock_listing.listing_url = "https://example.com/job"
        listings_by_id = {listing_id: mock_listing}

        mock_profile = MagicMock()
        mock_profile.id = str(uuid4())

        ml_result = MLScoringResult(
            score=85,
            is_disqualified=False,
            disqualification_reason=None,
            feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
            listing_id=listing_id,
        )

        results = service._convert_ml_results([ml_result], listings_by_id, mock_profile)

        assert len(results) == 1
        assert results[0].score == 85
        assert results[0].listing_id == listing_id
        assert results[0].feature_vector == (0.1, 0.2, 0.3, 0.4, 0.5)

    def test_convert_ml_results_filters_disqualified(self) -> None:
        """Test _convert_ml_results filters out disqualified results."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        service = JobMatcherService()

        listing_id = str(uuid4())
        mock_listing = MagicMock()
        mock_listing.listing_url = "https://example.com/job"
        listings_by_id = {listing_id: mock_listing}

        mock_profile = MagicMock()
        mock_profile.id = str(uuid4())

        ml_result = MLScoringResult(
            score=85,
            is_disqualified=True,
            disqualification_reason="Missing skills",
            listing_id=listing_id,
        )

        results = service._convert_ml_results([ml_result], listings_by_id, mock_profile)

        assert len(results) == 0

    def test_build_match_result_creates_correct_breakdown(self) -> None:
        """Test _build_match_result creates correct breakdown dict."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        service = JobMatcherService()

        listing_id = str(uuid4())
        mock_listing = MagicMock()
        mock_listing.listing_url = "https://example.com/job"
        listings_by_id = {listing_id: mock_listing}

        mock_profile = MagicMock()
        mock_profile.id = str(uuid4())

        ml_result = MLScoringResult(
            score=90,
            is_disqualified=False,
            disqualification_reason=None,
            feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
        )

        result = service._build_match_result(ml_result, listing_id, listings_by_id, mock_profile)

        assert result.score == 90
        assert result.pref_id == mock_profile.id
        assert result.listing_id == listing_id
        assert result.breakdown == {}
        assert result.feature_vector == (0.1, 0.2, 0.3, 0.4, 0.5)

    @pytest.mark.asyncio
    async def test_score_listings_batch_returns_empty_on_no_results(self) -> None:
        """Test _score_listings_batch returns empty when ML returns empty."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_ml = MagicMock()
        mock_ml.is_initialized = True
        mock_ml.extract_query_encoding_from_snapshot = MagicMock(return_value=MagicMock())
        mock_ml.score_listings_batch = AsyncMock(return_value=[])

        service = JobMatcherService()
        service._ml_service = mock_ml

        mock_profile = MagicMock()
        mock_profile.id = str(uuid4())

        results = await service._score_listings_batch({}, mock_profile)

        assert results == []

    @pytest.mark.asyncio
    async def test_score_listings_batch_raises_on_exception(self) -> None:
        """Test _score_listings_batch raises exception on ML failure."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_ml = MagicMock()
        mock_ml.is_initialized = True
        mock_ml.extract_query_encoding_from_snapshot = MagicMock(return_value=MagicMock())
        mock_ml.score_listings_batch = AsyncMock(side_effect=RuntimeError("ML failed"))

        listing_id = str(uuid4())
        mock_listing = MagicMock()
        mock_listing.listing_url = "https://example.com/job"
        listings_by_id = {listing_id: mock_listing}

        mock_profile = MagicMock()
        mock_profile.id = str(uuid4())

        service = JobMatcherService()
        service._ml_service = mock_ml

        with pytest.raises(RuntimeError, match="ML failed"):
            await service._score_listings_batch(listings_by_id, mock_profile)

    @pytest.mark.asyncio
    async def test_score_listings_batch_raises_when_ml_not_initialized(self) -> None:
        """Test _score_listings_batch raises when ML service not initialized."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        service = JobMatcherService()
        service._ml_service = None

        mock_profile = MagicMock()
        mock_profile.id = str(uuid4())

        with pytest.raises(RuntimeError, match="ML service not initialized"):
            await service._score_listings_batch({}, mock_profile)

    @pytest.mark.asyncio
    async def test_score_listings_batch_raises_when_query_encoding_missing(
        self,
    ) -> None:
        """Test _score_listings_batch raises DataNotAvailableError."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from nohiki_common_exceptions import DataNotAvailableError

        mock_ml = MagicMock()
        mock_ml.is_initialized = True
        mock_ml.extract_query_encoding_from_snapshot = MagicMock(return_value=None)

        service = JobMatcherService()
        service._ml_service = mock_ml

        mock_profile = MagicMock()
        mock_profile.id = str(uuid4())

        with pytest.raises(DataNotAvailableError):
            await service._score_listings_batch({}, mock_profile)


class TestJobMatcherServiceMatchJobBatchBehavior:
    """Tests for batch behavior of match_job_to_profiles."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_all_profiles_already_matched(self) -> None:
        """Profiles already having correlations are filtered; returns 0 for fully-duplicate batch."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        profile = MagicMock()
        profile.id = str(uuid4())
        profile.user_id = str(uuid4())

        mock_profile_repo = MagicMock()
        mock_profile_repo.get_active_profiles = AsyncMock(return_value=[profile])

        mock_match_repo = MagicMock()
        mock_match_repo.get_existing_pref_ids = AsyncMock(return_value={profile.id})

        mock_db = create_mock_session()
        mock_job = MagicMock()
        mock_job.id = uuid4()
        mock_job.listing_url = "https://example.com/job"

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.ProfileProjectionRepository",
                return_value=mock_profile_repo,
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
                return_value=mock_match_repo,
            ),
        ):
            service = JobMatcherService()
            result = await service.match_job_to_profiles(mock_db, mock_job, "corr-123")

        assert result == 0
        mock_match_repo.get_existing_pref_ids.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_ml_service_not_ready(self) -> None:
        """match_job_to_profiles returns 0 when ML service is not ready."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        profile = MagicMock()
        profile.id = str(uuid4())

        mock_profile_repo = MagicMock()
        mock_profile_repo.get_active_profiles = AsyncMock(return_value=[profile])

        mock_match_repo = MagicMock()
        mock_match_repo.get_existing_pref_ids = AsyncMock(return_value=set())

        mock_db = create_mock_session()
        mock_job = MagicMock()
        mock_job.id = uuid4()

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.ProfileProjectionRepository",
                return_value=mock_profile_repo,
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
                return_value=mock_match_repo,
            ),
        ):
            service = JobMatcherService()
            service._ml_service = None
            result = await service.match_job_to_profiles(mock_db, mock_job, "corr-123")

        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_all_profiles_score_none(self) -> None:
        """match_job_to_profiles returns 0 when scoring yields no valid results."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        profile = MagicMock()
        profile.id = str(uuid4())

        mock_profile_repo = MagicMock()
        mock_profile_repo.get_active_profiles = AsyncMock(return_value=[profile])

        mock_match_repo = MagicMock()
        mock_match_repo.get_existing_pref_ids = AsyncMock(return_value=set())

        mock_db = create_mock_session()
        mock_job = MagicMock()
        mock_job.id = uuid4()

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.ProfileProjectionRepository",
                return_value=mock_profile_repo,
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
                return_value=mock_match_repo,
            ),
        ):
            service = JobMatcherService()
            mock_ml = MagicMock()
            mock_ml.is_initialized = True
            mock_ml.extract_query_encoding_from_snapshot = MagicMock(return_value=None)
            service._ml_service = mock_ml
            result = await service.match_job_to_profiles(mock_db, mock_job, "corr-123")

        assert result == 0


class TestJobMatcherServiceScoreSingle:
    """Tests for _score_single method."""

    def test_raises_when_ml_service_none(self) -> None:
        """Test _score_single raises when ML service is None."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        service = JobMatcherService()
        service._ml_service = None

        mock_job = MagicMock()
        mock_profile = MagicMock()

        with pytest.raises(RuntimeError, match="ML service not initialized"):
            service._score_single(mock_job, "job-123", mock_profile)

    def test_returns_none_when_query_encoding_missing(self) -> None:
        """Test _score_single returns None when query encoding missing."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        service = JobMatcherService()

        mock_ml = MagicMock()
        mock_ml.extract_query_encoding_from_snapshot = MagicMock(return_value=None)
        service._ml_service = mock_ml

        mock_job = MagicMock()
        mock_profile = MagicMock()
        mock_profile.id = str(uuid4())

        result = service._score_single(mock_job, "job-123", mock_profile)

        assert result is None

    def test_returns_none_when_disqualified(self) -> None:
        """Test _score_single returns None when result is disqualified."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        service = JobMatcherService()

        mock_ml_result = MLScoringResult(
            score=0,
            is_disqualified=True,
            disqualification_reason="Missing skills",
        )  # feature_vector defaults to None for disqualified results

        mock_ml = MagicMock()
        mock_ml.extract_query_encoding_from_snapshot = MagicMock(return_value=MagicMock())
        mock_ml.score_with_inline_embeddings = MagicMock(return_value=mock_ml_result)
        service._ml_service = mock_ml

        mock_job = MagicMock()
        mock_job.listing_url = "https://example.com/job"
        mock_profile = MagicMock()
        mock_profile.id = str(uuid4())

        result = service._score_single(mock_job, "job-123", mock_profile)

        assert result is None


class TestJobMatcherServiceBuildMatchResultFromML:
    """Tests for _build_match_result_from_ml method."""

    def test_omits_non_finite_and_missing_public_scores(self) -> None:
        """Only finite normalized public dimensions are exposed."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        service = JobMatcherService()
        mock_profile = MagicMock(id=str(uuid4()))
        ml_result = MLScoringResult(
            score=85,
            is_disqualified=False,
            disqualification_reason=None,
            feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
        )

        result = service._build_match_result_from_ml(mock_profile, "job-123", "https://example.com/job", ml_result)

        assert result.score == 85
        assert result.breakdown == {}
        assert "ml_confidence" not in result.breakdown
        assert "rerank_score" not in result.breakdown
        assert "skills_cosine_sim" not in result.breakdown
        assert "feature_importances" not in result.breakdown
        assert result.feature_vector == (0.1, 0.2, 0.3, 0.4, 0.5)


class TestJobMatcherServiceMatchListingsToProfile:
    """Tests for match_listings_to_profile method (backfill)."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_listings_empty(self) -> None:
        """Test returns 0 when listings list is empty."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        service = JobMatcherService()
        mock_db = create_mock_session()
        mock_profile = MagicMock()

        result = await service.match_listings_to_profile(mock_db, [], mock_profile, "corr-123")

        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_all_listings_exist(self) -> None:
        """Test returns 0 when all listings already exist."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        service = JobMatcherService()

        mock_listing = MagicMock()
        mock_listing.id = uuid4()
        mock_listing.listing_url = "https://example.com/job"

        mock_repo = MagicMock()
        mock_repo.get_existing_listing_ids = AsyncMock(return_value=[str(mock_listing.id)])
        mock_repo.record_matches_batch = AsyncMock(return_value=0)

        with patch(
            "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository"
        ) as mock_repo_class:
            mock_repo_class.return_value = mock_repo

            mock_db = create_mock_session()
            mock_profile = MagicMock()
            mock_profile.id = str(uuid4())

            result = await service.match_listings_to_profile(mock_db, [mock_listing], mock_profile, "corr-123")

            assert result == 0

    @pytest.mark.asyncio
    async def test_processes_new_listings_successfully(self) -> None:
        """Test processes new listings and publishes events via outbox."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        mock_ml = MagicMock()
        mock_ml.is_initialized = True
        listing_id = uuid4()
        mock_ml.extract_query_encoding_from_snapshot = MagicMock(return_value=MagicMock())

        ml_result = MLScoringResult(
            score=85,
            is_disqualified=False,
            disqualification_reason=None,
            feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
            listing_id=str(listing_id),
        )
        mock_ml.score_listings_batch = AsyncMock(return_value=[ml_result])

        service = JobMatcherService()
        service._ml_service = mock_ml

        mock_listing = MagicMock()
        mock_listing.id = listing_id
        mock_listing.listing_url = "https://example.com/job"

        mock_repo = MagicMock()
        mock_repo.get_existing_listing_ids = AsyncMock(return_value=[])
        mock_repo.record_matches_batch_no_commit = AsyncMock(return_value=1)
        mock_repo.last_inserted_listing_ids = {str(listing_id)}

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository"
            ) as mock_repo_class,
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated"
            ) as mock_publish,
        ):
            mock_repo_class.return_value = mock_repo
            mock_publish.return_value = None

            mock_db = create_mock_session()
            mock_profile = MagicMock()
            mock_profile.id = str(uuid4())
            mock_profile.user_id = str(uuid4())

            result = await service.match_listings_to_profile(mock_db, [mock_listing], mock_profile, "corr-123")

            assert result == 1
            mock_repo.record_matches_batch_no_commit.assert_awaited_once()
            mock_publish.assert_awaited_once()
            mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_losing_concurrent_insert_emits_no_outbox_event(self) -> None:
        """A conflict-losing batch write must not publish an event for the winner's row."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        mock_ml = MagicMock()
        listing_id = uuid4()
        mock_ml.is_initialized = True
        mock_ml.extract_query_encoding_from_snapshot.return_value = MagicMock()
        mock_ml.score_listings_batch = AsyncMock(
            return_value=[
                MLScoringResult(
                    score=85,
                    is_disqualified=False,
                    disqualification_reason=None,
                    feature_vector=(0.1, 0.2, 0.3),
                    listing_id=str(listing_id),
                )
            ]
        )
        service = JobMatcherService(ml_scoring_service=mock_ml)
        listing = MagicMock()
        listing.id = listing_id
        listing.listing_url = "https://example.com/job"
        listing.skills_embedding = MagicMock()
        profile = MagicMock()
        profile.id = str(uuid4())
        profile.user_id = str(uuid4())
        repo = MagicMock()
        repo.get_existing_listing_ids = AsyncMock(return_value=[])
        repo.record_matches_batch_no_commit = AsyncMock(return_value=0)
        repo.last_inserted_listing_ids = set()
        db = create_mock_session()

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
                return_value=repo,
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated"
            ) as publish,
        ):
            inserted = await service.match_listings_to_profile(db, [listing], profile, "corr-123")

        assert inserted == 0
        publish.assert_not_awaited()
        db.commit.assert_awaited_once()


class TestJobMatcherServiceForceRescore:
    """Tests for the ListingUpdated re-scoring path (force_rescore=True).

     When enrichment completes and a ListingUpdated event arrives, the matcher
     must score ALL active profiles: not just those without prior correlations
    : and upsert the new ML score on top of any pre-enrichment row.
    """

    @pytest.mark.asyncio
    async def test_force_rescore_skips_existing_pref_filter(self) -> None:
        """force_rescore=True bypasses get_existing_pref_ids and rescores everyone."""
        from job_correlation_evaluation_service.services.match_types import (
            JobMatchResult,
        )
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )
        from nohiki.common.v1 import CorrelationStatus

        profile = MagicMock()
        profile.id = str(uuid4())
        profile.user_id = str(uuid4())

        mock_profile_repo = MagicMock()
        mock_profile_repo.get_active_profiles = AsyncMock(return_value=[profile])

        mock_match_repo = MagicMock()
        # Simulate a pre-existing correlation; force_rescore should ignore this.
        mock_match_repo.get_existing_pref_ids = AsyncMock(return_value={profile.id})
        mock_match_repo.upsert_match_no_commit = AsyncMock(return_value=(uuid4(), CorrelationStatus.APPLIED))
        mock_match_repo.record_match_no_commit = AsyncMock()

        mock_db = create_mock_session()
        mock_job = MagicMock()
        mock_job.id = uuid4()
        mock_job.listing_url = "https://example.com/job"
        mock_job.skills_embedding = MagicMock()  # _is_listing_enriched gate

        ml_result = MLScoringResult(
            score=88,
            is_disqualified=False,
            disqualification_reason=None,
            feature_vector=(0.1,) * 5,
        )

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.ProfileProjectionRepository",
                return_value=mock_profile_repo,
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
                return_value=mock_match_repo,
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated"
            ) as mock_publish,
        ):
            mock_publish.return_value = None

            service = JobMatcherService()
            mock_ml = MagicMock()
            mock_ml.is_initialized = True
            mock_ml.extract_query_encoding_from_snapshot = MagicMock(return_value=MagicMock())
            mock_ml.score_with_inline_embeddings = MagicMock(return_value=ml_result)
            service._ml_service = mock_ml

            result = await service.match_job_to_profiles(
                mock_db,
                mock_job,
                "corr-rescore",
                force_rescore=True,
            )

            assert result == 1
            # Force-rescore path must not consult existing correlations.
            mock_match_repo.get_existing_pref_ids.assert_not_awaited()
            mock_match_repo.upsert_match_no_commit.assert_awaited_once()
            mock_match_repo.record_match_no_commit.assert_not_awaited()
            mock_publish.assert_awaited_once()
            mock_db.commit.assert_awaited_once()
            # Sanity: an actual JobMatchResult was passed downstream.
            await_args = mock_publish.await_args
            assert await_args is not None
            published_arg = await_args.args[1]
            assert isinstance(published_arg, JobMatchResult)
            assert published_arg.score == 88

    @pytest.mark.asyncio
    async def test_default_path_uses_record_match(self) -> None:
        """force_rescore=False (default) inserts new rows via record_match_no_commit."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        profile = MagicMock()
        profile.id = str(uuid4())
        profile.user_id = str(uuid4())

        mock_profile_repo = MagicMock()
        mock_profile_repo.get_active_profiles = AsyncMock(return_value=[profile])

        mock_match_repo = MagicMock()
        mock_match_repo.get_existing_pref_ids = AsyncMock(return_value=set())
        mock_match_repo.upsert_match_no_commit = AsyncMock()
        mock_match_repo.record_match_no_commit = AsyncMock()

        mock_db = create_mock_session()
        mock_job = MagicMock()
        mock_job.id = uuid4()
        mock_job.listing_url = "https://example.com/job"
        mock_job.skills_embedding = MagicMock()

        ml_result = MLScoringResult(
            score=70,
            is_disqualified=False,
            disqualification_reason=None,
            feature_vector=(0.1,) * 5,
        )

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.ProfileProjectionRepository",
                return_value=mock_profile_repo,
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
                return_value=mock_match_repo,
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated"
            ) as mock_publish,
        ):
            mock_publish.return_value = None

            service = JobMatcherService()
            mock_ml = MagicMock()
            mock_ml.is_initialized = True
            mock_ml.extract_query_encoding_from_snapshot = MagicMock(return_value=MagicMock())
            mock_ml.score_with_inline_embeddings = MagicMock(return_value=ml_result)
            service._ml_service = mock_ml

            result = await service.match_job_to_profiles(mock_db, mock_job, "corr-default")

            assert result == 1
            mock_match_repo.get_existing_pref_ids.assert_awaited_once()
            mock_match_repo.record_match_no_commit.assert_awaited_once()
            mock_match_repo.upsert_match_no_commit.assert_not_awaited()


class TestJobMatcherServiceBackfillRescoring:
    """Regression tests for missing-only versus force-rescore backfills."""

    @pytest.mark.asyncio
    async def test_created_backfill_skips_existing_correlation(self) -> None:
        """PrefCreated backfill must not duplicate an existing correlation."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        listing_id = uuid4()
        profile = MagicMock(id=str(uuid4()), user_id=str(uuid4()))
        listing = MagicMock(id=listing_id, listing_url="https://example.test/job")
        db = create_mock_session()
        mock_repo = MagicMock()
        mock_repo.get_existing_listing_ids = AsyncMock(return_value={str(listing_id)})
        mock_repo.record_matches_with_listing_ids_no_commit = AsyncMock()

        with patch(
            "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
            return_value=mock_repo,
        ):
            service = JobMatcherService()
            result = await service.match_listings_to_profile(
                db,
                [listing],
                profile,
                "created-backfill",
            )

        assert result == 0
        mock_repo.get_existing_listing_ids.assert_awaited_once()
        mock_repo.record_matches_with_listing_ids_no_commit.assert_not_awaited()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_updated_backfill_rescores_and_upserts_existing_rows(self) -> None:
        """PrefUpdated backfill refreshes stale and zero-score correlations."""
        from job_correlation_evaluation_service.services.match_types import (
            JobMatchResult,
        )
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from nohiki.common.v1 import CorrelationStatus

        listing_ids = [uuid4(), uuid4()]
        profile = MagicMock(id=str(uuid4()), user_id=str(uuid4()))
        listings = cast(
            list[ListingSnapshot],
            [
                MagicMock(
                    id=listing_id,
                    listing_url=f"https://example.test/job/{index}",
                    skills_embedding=[0.1],
                )
                for index, listing_id in enumerate(listing_ids)
            ],
        )
        results = [
            JobMatchResult(
                pref_id=profile.id,
                listing_id=str(listing_ids[0]),
                listing_url=listings[0].listing_url,
                score=91,
                breakdown={},
                feature_schema_version="v-next",
                role_relevance_raw=0.9,
                ranking_index=1.0,
                factors=(),
                feature_vector=(0.9, 0.1),
            ),
            JobMatchResult(
                pref_id=profile.id,
                listing_id=str(listing_ids[1]),
                listing_url=listings[1].listing_url,
                score=0,
                breakdown={},
                feature_schema_version="v-next",
                role_relevance_raw=0.0,
                ranking_index=0.0,
                factors=(),
                feature_vector=(0.0, 0.0),
            ),
        ]
        db = create_mock_session()
        mock_repo = MagicMock()
        mock_repo.get_existing_listing_ids = AsyncMock(return_value={str(listing_ids[0])})
        persisted_ids = [uuid4(), uuid4()]
        persisted_statuses = [CorrelationStatus.APPLIED, CorrelationStatus.DISMISSED]
        mock_repo.upsert_matches_with_listing_ids_no_commit = AsyncMock(
            return_value={
                result.listing_id: (persisted_id, persisted_status)
                for result, persisted_id, persisted_status in zip(
                    results, persisted_ids, persisted_statuses, strict=True
                )
            }
        )

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
                return_value=mock_repo,
            ),
            patch.object(
                JobMatcherService,
                "_score_listings_batch",
                new=AsyncMock(return_value=results),
            ),
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated",
                new=AsyncMock(),
            ) as mock_publish,
        ):
            service = JobMatcherService()
            count = await service.match_listings_to_profile(
                db,
                listings,
                profile,
                "updated-backfill",
                force_rescore=True,
            )

        assert count == 2
        mock_repo.get_existing_listing_ids.assert_not_awaited()
        mock_repo.upsert_matches_with_listing_ids_no_commit.assert_awaited_once()
        assert mock_publish.await_count == 2
        published_results = {call.args[1].listing_id: call.args[1] for call in mock_publish.await_args_list}
        assert set(published_results) == {result.listing_id for result in results}
        for result, persisted_id, persisted_status in zip(results, persisted_ids, persisted_statuses, strict=True):
            assert published_results[result.listing_id].correlation_id == persisted_id
            assert published_results[result.listing_id].status == persisted_status
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_force_backfill_scores_enriched_and_zeroes_only_existing_unenriched(
        self,
    ) -> None:
        """Force backfill never inserts a new unenriched row or skips stale existing data."""
        from job_correlation_evaluation_service.services.match_types import (
            JobMatchResult,
        )
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from nohiki.common.v1 import CorrelationStatus

        listing_ids = [uuid4(), uuid4(), uuid4()]
        enriched_id, existing_unenriched_id, new_unenriched_id = listing_ids
        profile = MagicMock(id=str(uuid4()), user_id=str(uuid4()))
        listings = cast(
            list[ListingSnapshot],
            [
                MagicMock(
                    id=enriched_id,
                    listing_url="https://example.test/enriched",
                    skills_embedding=[0.1],
                ),
                MagicMock(
                    id=existing_unenriched_id,
                    listing_url="https://example.test/stale",
                    skills_embedding=None,
                ),
                MagicMock(
                    id=new_unenriched_id,
                    listing_url="https://example.test/new",
                    skills_embedding=None,
                ),
            ],
        )
        scored = JobMatchResult(
            pref_id=profile.id,
            listing_id=str(enriched_id),
            listing_url=listings[0].listing_url,
            score=93,
            breakdown={},
            feature_schema_version="v-next",
            role_relevance_raw=0.9,
            ranking_index=1.0,
            factors=(),
            feature_vector=(0.9, 0.1),
        )
        db = create_mock_session()
        mock_repo = MagicMock()
        mock_repo.get_existing_listing_ids = AsyncMock(return_value={str(existing_unenriched_id)})
        persisted = {
            str(enriched_id): (uuid4(), CorrelationStatus.EVALUATED),
            str(existing_unenriched_id): (uuid4(), CorrelationStatus.APPLIED),
        }
        mock_repo.upsert_matches_with_listing_ids_no_commit = AsyncMock(return_value=persisted)

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository",
                return_value=mock_repo,
            ),
            patch.object(
                JobMatcherService,
                "_score_listings_batch",
                new=AsyncMock(return_value=[scored]),
            ) as mock_score,
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated",
                new=AsyncMock(),
            ) as mock_publish,
        ):
            count = await JobMatcherService().match_listings_to_profile(
                db,
                listings,
                profile,
                "mixed-enrichment",
                force_rescore=True,
            )

        assert count == 2
        mock_score.assert_awaited_once()
        score_call = mock_score.await_args
        assert score_call is not None
        scored_input = score_call.args[0]
        assert set(scored_input) == {str(enriched_id)}
        mock_repo.get_existing_listing_ids.assert_awaited_once()
        existing_call = mock_repo.get_existing_listing_ids.await_args
        assert existing_call is not None
        queried_ids = set(existing_call.args[1])
        assert queried_ids == {str(existing_unenriched_id), str(new_unenriched_id)}
        upsert_call = mock_repo.upsert_matches_with_listing_ids_no_commit.await_args
        assert upsert_call is not None
        upserted_results = upsert_call.args[0]
        assert {result.listing_id for result in upserted_results} == {
            str(enriched_id),
            str(existing_unenriched_id),
        }
        zero_result = next(result for result in upserted_results if result.listing_id == str(existing_unenriched_id))
        assert zero_result.score == 0
        assert zero_result.feature_vector is None
        assert mock_publish.await_count == 2
        assert all(call.args[2].listing_id != str(new_unenriched_id) for call in mock_publish.await_args_list)

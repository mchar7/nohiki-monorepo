"""Unit tests for MLScoringService error handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import (
    FactorAttribution,
    ScoredCandidate,
)
from job_correlation_evaluation_service.services.scoring_service import (
    MLScoringService,
)


class TestMLScoringServiceErrorHandling:
    """Tests for MLScoringService error handling."""

    @pytest.fixture
    def mock_pipeline(self) -> MagicMock:
        """Create mock pipeline."""
        return MagicMock()

    @pytest.fixture
    def ml_service(self, mock_pipeline: MagicMock) -> MLScoringService:
        """Create ML scoring service."""
        service = MLScoringService(mock_pipeline)
        service.initialize()
        return service

    @pytest.fixture
    def mock_job(self) -> MagicMock:
        """Create mock job."""
        job = MagicMock()
        job.id = "job-123"
        job.title = "Software Engineer"
        job.description = "Python developer"
        return job

    @pytest.fixture
    def mock_profile(self) -> MagicMock:
        """Create mock profile."""
        profile = MagicMock()
        profile.id = "profile-456"
        profile.disallowed_keywords = []
        profile.search_keywords = ["python"]
        return profile

    def test_check_disqualification_with_keywords(
        self,
        ml_service: MLScoringService,
        mock_job: MagicMock,
        mock_profile: MagicMock,
    ) -> None:
        """Test _check_disqualification with disallowed keywords."""
        mock_profile.disallowed_keywords = ["senior", "director"]
        mock_job.title = "Senior Software Engineer"
        mock_job.description = "Looking for a senior developer"

        is_disqualified, reason = ml_service._check_disqualification(mock_job, mock_profile)

        assert is_disqualified is True
        assert reason is not None
        assert "senior" in reason.lower()

    def test_check_disqualification_no_match(
        self,
        ml_service: MLScoringService,
        mock_job: MagicMock,
        mock_profile: MagicMock,
    ) -> None:
        """Test _check_disqualification with no matching keywords."""
        mock_profile.disallowed_keywords = ["manager", "director"]
        mock_job.title = "Software Engineer"
        mock_job.description = "Python developer role"

        is_disqualified, reason = ml_service._check_disqualification(mock_job, mock_profile)

        assert is_disqualified is False
        assert reason is None

    def test_check_disqualification_no_keywords(
        self,
        ml_service: MLScoringService,
        mock_job: MagicMock,
        mock_profile: MagicMock,
    ) -> None:
        """Test _check_disqualification with no disallowed keywords."""
        mock_profile.disallowed_keywords = []
        mock_job.title = "Software Engineer"
        mock_job.description = "Python developer role"

        is_disqualified, reason = ml_service._check_disqualification(mock_job, mock_profile)

        assert is_disqualified is False
        assert reason is None

    def test_initialize_error_handling(
        self,
        mock_pipeline: MagicMock,
    ) -> None:
        """Test initialize handles errors properly."""
        service = MLScoringService(mock_pipeline)

        service.initialize()

        assert service.is_initialized is True

    @pytest.mark.asyncio
    async def test_close_calls_pipeline_close(
        self,
        ml_service: MLScoringService,
        mock_pipeline: MagicMock,
    ) -> None:
        """Test close method calls pipeline close."""
        from unittest.mock import AsyncMock

        mock_pipeline.close = AsyncMock()

        await ml_service.close()

        mock_pipeline.close.assert_awaited_once()


class TestMLScoringServiceInitialization:
    """Tests for MLScoringService initialization."""

    def test_initialize_idempotent(self) -> None:
        """Test initialize is idempotent when already initialized."""
        mock_pipeline = MagicMock()
        service = MLScoringService(mock_pipeline)
        service.initialize()

        # Second initialize should not raise and should log warning
        service.initialize()

        assert service.is_initialized is True


class TestMLScoringServiceScoreListingsBatch:
    """Tests for score_listings_batch method."""

    @pytest.fixture
    def initialized_service(self) -> tuple[MLScoringService, MagicMock]:
        """Create initialized service with mock pipeline."""
        mock_pipeline = MagicMock()
        service = MLScoringService(mock_pipeline)
        service.initialize()
        return service, mock_pipeline

    def test_raises_when_not_initialized(self) -> None:
        """Test raises MLScoringServiceError when not initialized."""
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringServiceError,
        )

        mock_pipeline = MagicMock()
        service = MLScoringService(mock_pipeline)
        # Don't initialize

        async def _run_test() -> None:
            await service.score_listings_batch({}, MagicMock(), MagicMock())

        import asyncio

        with pytest.raises(MLScoringServiceError, match="Service not initialized"):
            asyncio.run(_run_test())

    @pytest.mark.asyncio
    async def test_returns_empty_when_listings_empty(
        self, initialized_service: tuple[MLScoringService, MagicMock]
    ) -> None:
        """Test returns empty list when listings dict is empty."""
        service, _ = initialized_service

        result = await service.score_listings_batch({}, MagicMock(), MagicMock())

        assert result == []

    @pytest.mark.asyncio
    async def test_maps_current_score_and_explanation_fields(
        self, initialized_service: tuple[MLScoringService, MagicMock]
    ) -> None:
        """Pipeline candidates map score, role explanation, ranking, and factors to service results."""
        service, mock_pipeline = initialized_service
        factors = (FactorAttribution("skills", 0.8, 75, 1.5),)
        mock_candidate = ScoredCandidate(
            entity_id="job-123",
            maxsim_score=0.75,
            rerank_score=0.5,
            rank_index=0.8,
            final_score=85,
            feature_vector=(0.1, 0.2),
            factor_attributions=factors,
            role_relevance_raw=67.0,
        )
        mock_pipeline.score_listings_by_ids = AsyncMock(return_value=[mock_candidate])

        result = await service.score_listings_batch({"job-123": MagicMock()}, MagicMock(), MagicMock())

        assert len(result) == 1
        assert result[0].score == 85
        assert result[0].is_disqualified is False
        assert result[0].listing_id == "job-123"
        assert result[0].role_relevance_raw == pytest.approx(67.0)
        assert result[0].ranking_index == pytest.approx(0.8)
        assert result[0].feature_vector == (0.1, 0.2)
        assert result[0].factors == factors
        mock_pipeline.score_listings_by_ids.assert_awaited_once()


class TestMLScoringServiceExtractQueryEncodingFromSnapshot:
    """Tests for extract_query_encoding_from_snapshot method."""

    def test_returns_none_when_not_initialized(self) -> None:
        """Test returns None when service not initialized."""
        mock_pipeline = MagicMock()
        service = MLScoringService(mock_pipeline)

        mock_profile = MagicMock()
        result = service.extract_query_encoding_from_snapshot(mock_profile)

        assert result is None

    def test_delegates_to_pipeline(self) -> None:
        """Test delegates to pipeline when initialized."""
        mock_pipeline = MagicMock()
        mock_encoding = MagicMock()
        mock_pipeline.extract_query_encoding_from_snapshot.return_value = mock_encoding

        service = MLScoringService(mock_pipeline)
        service.initialize()

        mock_profile = MagicMock()
        result = service.extract_query_encoding_from_snapshot(mock_profile)

        assert result is mock_encoding
        mock_pipeline.extract_query_encoding_from_snapshot.assert_called_once_with(mock_profile)


class TestMLScoringServiceScoreWithInlineEmbeddings:
    """Tests for score_with_inline_embeddings method."""

    def test_raises_when_not_initialized(self) -> None:
        """Test raises MLScoringServiceError when not initialized."""
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringServiceError,
        )

        mock_pipeline = MagicMock()
        service = MLScoringService(mock_pipeline)

        with pytest.raises(MLScoringServiceError, match="Service not initialized"):
            service.score_with_inline_embeddings(MagicMock(), MagicMock(), MagicMock())

    def test_returns_disqualified_result(self) -> None:
        """Test returns disqualified result when keywords match."""
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        mock_pipeline = MagicMock()
        service = MLScoringService(mock_pipeline)
        service.initialize()

        mock_job = MagicMock()
        mock_job.title = "Senior Software Engineer"
        mock_job.description = "Python role"
        mock_job.company_name = "Tech Co"
        mock_job.required_skills = ["python"]

        mock_profile = MagicMock()
        mock_profile.disallowed_keywords = ["senior"]

        mock_encoding = MagicMock()

        result = service.score_with_inline_embeddings(mock_job, mock_profile, mock_encoding)

        assert isinstance(result, MLScoringResult)
        assert result.is_disqualified is True
        assert result.score == 0
        assert "senior" in (result.disqualification_reason or "").lower()
        assert result.feature_vector is None


class TestMLScoringServiceClose:
    """Tests for close behavior."""

    @pytest.mark.asyncio
    async def test_close_delegates_to_required_pipeline(self) -> None:
        """Close delegates to the pipeline supplied at construction."""
        mock_pipeline = MagicMock()
        mock_pipeline.close = AsyncMock()
        service = MLScoringService(mock_pipeline)

        await service.close()

        mock_pipeline.close.assert_awaited_once()

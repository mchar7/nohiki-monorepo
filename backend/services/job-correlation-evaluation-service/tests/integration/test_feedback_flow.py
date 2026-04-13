"""Integration tests for feedback collection and training data export flows.

Tests verify the complete feedback loop from recording user interactions
to exporting training data for L2R model retraining.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from job_correlation_evaluation_service.repositories.correlation_repository import (
    CorrelationNotFoundError,
    CorrelationRepository,
)
from job_correlation_evaluation_service.services.feedback_service import (
    CorrelationFeedbackService,
)
from job_correlation_evaluation_service.services.scoring.constants import FEATURE_COUNT
from nohiki.common.v1 import UserFeedback
from nohiki.job.correlation.v1 import FeedbackType
from pytest_unused_fixtures import ignore_unused_fixture


@dataclass(frozen=True)
class CorrelationSpec:
    """Specification for creating mock correlations in tests."""

    is_applied: bool = False
    is_viewed: bool = False
    is_dismissed: bool = False
    user_feedback: UserFeedback | None = None
    feature_vector: list[float] | None = None
    user_id: str | None = None


@pytest.mark.integration
class TestFeedbackRecordingFlow:
    """Integration tests for the feedback recording flow."""

    @pytest.mark.asyncio
    async def test_view_then_apply_flow(self) -> None:
        """Test common flow: user views a job then applies."""
        mock_repository = AsyncMock(spec=CorrelationRepository)
        feedback_service = CorrelationFeedbackService(repository=mock_repository)

        sample_correlation = MagicMock()
        sample_correlation.id = uuid4()
        sample_correlation.user_id = uuid4()
        sample_correlation.listing_id = uuid4()
        sample_correlation.pref_id = uuid4()
        sample_correlation.is_viewed = False
        sample_correlation.is_applied = False
        sample_correlation.is_dismissed = False
        sample_correlation.user_feedback = None
        sample_correlation.feature_vector = [0.5] * FEATURE_COUNT
        sample_correlation.created_at = datetime.now(UTC)

        mock_repository.update.return_value = sample_correlation

        # Step 1: User views the job
        await feedback_service.record_feedback(
            correlation_id=sample_correlation.id,
            feedback_type=FeedbackType.VIEWED,
        )

        # Verify viewed was set
        mock_repository.update.assert_called_with(sample_correlation.id, is_viewed=True)

        # Step 2: User applies to the job
        await feedback_service.record_feedback(
            correlation_id=sample_correlation.id,
            feedback_type=FeedbackType.APPLIED,
        )

        # Verify applied and viewed were set
        mock_repository.update.assert_called_with(
            sample_correlation.id,
            is_applied=True,
            is_viewed=True,
        )

    @pytest.mark.asyncio
    async def test_view_then_dismiss_flow(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
        sample_correlation: MagicMock,
    ) -> None:
        """Test flow: user views a job then dismisses it."""
        mock_repository.update.return_value = sample_correlation

        # Step 1: User views the job
        await feedback_service.record_feedback(
            correlation_id=sample_correlation.id,
            feedback_type=FeedbackType.VIEWED,
        )

        # Step 2: User dismisses the job
        await feedback_service.record_feedback(
            correlation_id=sample_correlation.id,
            feedback_type=FeedbackType.DISMISSED,
        )

        mock_repository.update.assert_called_with(sample_correlation.id, is_dismissed=True)

    @pytest.mark.asyncio
    async def test_save_and_like_flow(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
        sample_correlation: MagicMock,
    ) -> None:
        """Test flow: user saves a job (which implies they liked it)."""
        mock_repository.update.return_value = sample_correlation

        await feedback_service.record_feedback(
            correlation_id=sample_correlation.id,
            feedback_type=FeedbackType.SAVED,
        )

        mock_repository.update.assert_called_with(
            sample_correlation.id,
            user_feedback=UserFeedback.POSITIVE,
            is_viewed=True,
        )

    @pytest.mark.asyncio
    async def test_nonexistent_correlation_raises_error(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test recording feedback for nonexistent correlation raises error."""
        correlation_id = uuid4()
        mock_repository.update.side_effect = CorrelationNotFoundError(correlation_id)

        with pytest.raises(CorrelationNotFoundError):
            await feedback_service.record_feedback(
                correlation_id=correlation_id,
                feedback_type=FeedbackType.VIEWED,
            )


@pytest.mark.integration
class TestTrainingDataExportFlow:
    """Integration tests for training data export flow."""

    def _make_correlation(self, spec: CorrelationSpec | None = None) -> MagicMock:
        """Create mock correlation from spec."""
        spec = spec or CorrelationSpec()
        corr = MagicMock()
        corr.id = uuid4()
        corr.user_id = spec.user_id or uuid4()
        corr.is_applied = spec.is_applied
        corr.is_viewed = spec.is_viewed
        corr.is_dismissed = spec.is_dismissed
        corr.user_feedback = spec.user_feedback
        corr.feature_vector = spec.feature_vector
        corr.created_at = datetime.now(UTC)
        return corr

    @pytest.mark.asyncio
    async def test_export_diverse_feedback_types(self) -> None:
        """Test export handles diverse feedback types correctly."""
        mock_repository = AsyncMock(spec=CorrelationRepository)
        feedback_service = CorrelationFeedbackService(repository=mock_repository)

        correlations = [
            self._make_correlation(CorrelationSpec(is_applied=True, feature_vector=[0.5] * FEATURE_COUNT)),
            self._make_correlation(
                CorrelationSpec(
                    user_feedback=UserFeedback.POSITIVE,
                    feature_vector=[0.6] * FEATURE_COUNT,
                )
            ),
            self._make_correlation(CorrelationSpec(is_viewed=True, feature_vector=[0.4] * FEATURE_COUNT)),
            self._make_correlation(CorrelationSpec(is_dismissed=True, feature_vector=[0.3] * FEATURE_COUNT)),
            self._make_correlation(
                CorrelationSpec(
                    user_feedback=UserFeedback.NEGATIVE,
                    feature_vector=[0.2] * FEATURE_COUNT,
                )
            ),
        ]
        mock_repository.get_for_training.return_value = correlations

        samples = await feedback_service.export_training_data()

        assert len(samples) == 5

        # Verify labels are correct
        labels = [s["label"] for s in samples]
        assert 5.0 in labels  # applied
        assert 4.0 in labels  # positive feedback
        assert 2.0 in labels  # viewed
        assert 0.5 in labels  # dismissed
        assert 0.0 in labels  # negative feedback

    @pytest.mark.asyncio
    async def test_export_groups_by_user(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test export includes query_id (user_id) for LambdaMART grouping."""
        user_id = str(uuid4())
        correlations = [
            self._make_correlation(
                CorrelationSpec(
                    is_applied=True,
                    feature_vector=[0.5] * FEATURE_COUNT,
                    user_id=user_id,
                )
            ),
            self._make_correlation(
                CorrelationSpec(
                    is_viewed=True,
                    feature_vector=[0.4] * FEATURE_COUNT,
                    user_id=user_id,
                )
            ),
        ]
        mock_repository.get_for_training.return_value = correlations

        samples = await feedback_service.export_training_data()

        # All samples should have same query_id
        query_ids = [s["query_id"] for s in samples]
        assert all(qid == user_id for qid in query_ids)

    @pytest.mark.asyncio
    async def test_export_date_filtering(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test export respects date range filters."""
        mock_repository.get_for_training.return_value = []

        min_date = datetime.now(UTC) - timedelta(days=30)
        max_date = datetime.now(UTC)

        await feedback_service.export_training_data(
            min_date=min_date,
            max_date=max_date,
        )

        mock_repository.get_for_training.assert_called_once_with(
            min_date=min_date,
            max_date=max_date,
            limit=10000,
        )

    @pytest.mark.asyncio
    async def test_export_skips_invalid_samples(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test export skips samples without features or labels."""
        correlations = [
            # Valid: has features and feedback
            self._make_correlation(CorrelationSpec(is_applied=True, feature_vector=[0.5] * FEATURE_COUNT)),
            # Invalid: has feedback but no features
            self._make_correlation(CorrelationSpec(is_applied=True, feature_vector=None)),
            # Invalid: has features but no feedback signal
            self._make_correlation(CorrelationSpec(feature_vector=[0.5] * FEATURE_COUNT)),
        ]
        mock_repository.get_for_training.return_value = correlations

        samples = await feedback_service.export_training_data()

        # Only the valid sample should be exported
        assert len(samples) == 1
        assert samples[0]["label"] == pytest.approx(5.0)


@pytest.mark.integration
class TestFeedbackStatsFlow:
    """Integration tests for feedback statistics retrieval."""

    @pytest.fixture
    @ignore_unused_fixture
    def mock_repository(self) -> AsyncMock:
        """Create mock repository."""
        return AsyncMock(spec=CorrelationRepository)

    @pytest.fixture
    @ignore_unused_fixture
    def feedback_service(self, mock_repository: AsyncMock) -> CorrelationFeedbackService:
        """Create feedback service."""
        return CorrelationFeedbackService(repository=mock_repository)

    @pytest.mark.asyncio
    async def test_get_stats_returns_complete_structure(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test get_stats returns expected structure."""
        mock_repository.get_feedback_stats.return_value = {
            "total_feedback_count": 1500,
            "feedback_by_type": {
                "viewed": 1000,
                "applied": 200,
                "dismissed": 150,
                "user_feedback_positive": 100,
                "user_feedback_negative": 50,
            },
            "training_samples_available": 800,
        }

        stats = await feedback_service.get_stats()

        assert "total_feedback_count" in stats
        assert "feedback_by_type" in stats
        assert "training_samples_available" in stats
        assert stats["total_feedback_count"] == 1500
        assert stats["training_samples_available"] == 800


@pytest.mark.integration
class TestLabelPrecedence:
    """Integration tests for label computation precedence rules."""

    @pytest.fixture
    @ignore_unused_fixture
    def feedback_service(self) -> CorrelationFeedbackService:
        """Create feedback service."""
        return CorrelationFeedbackService(repository=AsyncMock())

    def _make_correlation(self, **kwargs: bool | UserFeedback | None) -> MagicMock:
        """Create mock correlation with specified attributes."""
        corr = MagicMock()
        corr.is_applied = kwargs.get("is_applied", False)
        corr.is_viewed = kwargs.get("is_viewed", False)
        corr.is_dismissed = kwargs.get("is_dismissed", False)
        corr.user_feedback = kwargs.get("user_feedback")
        return corr

    def test_applied_takes_precedence_over_all(
        self,
        feedback_service: CorrelationFeedbackService,
    ) -> None:
        """Test applied (5.0) takes precedence over all other signals."""
        corr = self._make_correlation(
            is_applied=True,
            is_viewed=True,
            is_dismissed=True,
            user_feedback=UserFeedback.POSITIVE,
        )

        label = feedback_service._compute_label(corr)
        assert label == pytest.approx(5.0)

    def test_positive_feedback_over_viewed(
        self,
        feedback_service: CorrelationFeedbackService,
    ) -> None:
        """Test positive feedback (4.0) takes precedence over viewed (2.0)."""
        corr = self._make_correlation(
            is_viewed=True,
            user_feedback=UserFeedback.POSITIVE,
        )

        label = feedback_service._compute_label(corr)
        assert label == pytest.approx(4.0)

    def test_dismissed_over_viewed(
        self,
        feedback_service: CorrelationFeedbackService,
    ) -> None:
        """Test dismissed (0.5) overrides viewed (2.0)."""
        corr = self._make_correlation(
            is_viewed=True,
            is_dismissed=True,
        )

        label = feedback_service._compute_label(corr)
        assert label == pytest.approx(0.5)

    def test_negative_feedback_is_lowest(
        self,
        feedback_service: CorrelationFeedbackService,
    ) -> None:
        """Test negative feedback (0.0) is lowest possible label."""
        corr = self._make_correlation(
            user_feedback=UserFeedback.NEGATIVE,
        )

        label = feedback_service._compute_label(corr)
        assert label == pytest.approx(0.0)

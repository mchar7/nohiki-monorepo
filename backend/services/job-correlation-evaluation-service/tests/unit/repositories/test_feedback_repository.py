"""Unit tests for FeedbackRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from job_correlation_evaluation_service.repositories.feedback_repository import (
    FeedbackRepository,
    ListingFeedbackAggregate,
    ManualAdjustmentCreate,
)
from nohiki.feedback.v1 import ScoreFeedbackType
from nohiki_db_utils.testing import create_mock_session


class TestListingFeedbackAggregate:
    """Tests for ListingFeedbackAggregate dataclass."""

    def test_total_count(self) -> None:
        """Test total_count property sums all feedback types."""
        agg = ListingFeedbackAggregate(
            listing_id=uuid4(),
            good_count=5,
            too_high_count=3,
            too_low_count=2,
        )
        assert agg.total_count == 10

    def test_total_count_zeros(self) -> None:
        """Test total_count with all zeros."""
        agg = ListingFeedbackAggregate(
            listing_id=uuid4(),
            good_count=0,
            too_high_count=0,
            too_low_count=0,
        )
        assert agg.total_count == 0

    def test_quality_signal_all_good(self) -> None:
        """Test quality_signal when all feedback is GOOD."""
        agg = ListingFeedbackAggregate(
            listing_id=uuid4(),
            good_count=10,
            too_high_count=0,
            too_low_count=0,
        )
        assert agg.quality_signal == pytest.approx(0.0)

    def test_quality_signal_all_too_high(self) -> None:
        """Test quality_signal when all feedback is TOO_HIGH (low quality)."""
        agg = ListingFeedbackAggregate(
            listing_id=uuid4(),
            good_count=0,
            too_high_count=10,
            too_low_count=0,
        )
        assert agg.quality_signal == pytest.approx(-1.0)

    def test_quality_signal_all_too_low(self) -> None:
        """Test quality_signal when all feedback is TOO_LOW (high quality)."""
        agg = ListingFeedbackAggregate(
            listing_id=uuid4(),
            good_count=0,
            too_high_count=0,
            too_low_count=10,
        )
        assert agg.quality_signal == pytest.approx(1.0)

    def test_quality_signal_balanced(self) -> None:
        """Test quality_signal with balanced TOO_HIGH and TOO_LOW."""
        agg = ListingFeedbackAggregate(
            listing_id=uuid4(),
            good_count=0,
            too_high_count=5,
            too_low_count=5,
        )
        assert agg.quality_signal == pytest.approx(0.0)

    def test_quality_signal_empty(self) -> None:
        """Test quality_signal with no feedback returns 0."""
        agg = ListingFeedbackAggregate(
            listing_id=uuid4(),
            good_count=0,
            too_high_count=0,
            too_low_count=0,
        )
        assert agg.quality_signal == pytest.approx(0.0)

    def test_quality_signal_mixed(self) -> None:
        """Test quality_signal with mixed feedback."""
        agg = ListingFeedbackAggregate(
            listing_id=uuid4(),
            good_count=2,
            too_high_count=3,
            too_low_count=5,
        )
        # Expected: (too_low - too_high) / total = (5-3)/10 = 0.2
        assert agg.quality_signal == pytest.approx(0.2)

    def test_is_frozen_dataclass(self) -> None:
        """Test that ListingFeedbackAggregate is a frozen dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(ListingFeedbackAggregate)
        params = getattr(ListingFeedbackAggregate, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestFeedbackRepository:
    """Tests for FeedbackRepository."""


class TestCreateAsymmetricFeedback:
    """Tests for create_asymmetric_feedback method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session with synchronous add method."""
        session = create_mock_session()
        session.add = MagicMock()
        return session

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> FeedbackRepository:
        """Create repository with mock session."""
        return FeedbackRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_create_good_feedback(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test creating GOOD feedback."""
        correlation_id = uuid4()
        user_id = uuid4()

        await repository.create_asymmetric_feedback(
            correlation_id=correlation_id,
            user_id=user_id,
            feedback_type=ScoreFeedbackType.GOOD,
        )

        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once()

        added_model = mock_session.add.call_args[0][0]
        assert added_model.correlation_id == correlation_id
        assert added_model.user_id == user_id
        assert added_model.feedback_type == ScoreFeedbackType.GOOD.name

    @pytest.mark.asyncio
    async def test_create_too_high_feedback(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test creating TOO_HIGH feedback."""
        correlation_id = uuid4()
        user_id = uuid4()

        await repository.create_asymmetric_feedback(
            correlation_id=correlation_id,
            user_id=user_id,
            feedback_type=ScoreFeedbackType.TOO_HIGH,
        )

        added_model = mock_session.add.call_args[0][0]
        assert added_model.feedback_type == ScoreFeedbackType.TOO_HIGH.name

    @pytest.mark.asyncio
    async def test_create_too_low_feedback(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test creating TOO_LOW feedback."""
        correlation_id = uuid4()
        user_id = uuid4()

        await repository.create_asymmetric_feedback(
            correlation_id=correlation_id,
            user_id=user_id,
            feedback_type=ScoreFeedbackType.TOO_LOW,
        )

        added_model = mock_session.add.call_args[0][0]
        assert added_model.feedback_type == ScoreFeedbackType.TOO_LOW.name

    @pytest.mark.asyncio
    async def test_duplicate_request_returns_original_feedback_without_adding_a_row(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Retrying one request ID resolves to the original feedback record."""
        existing = MagicMock()
        selected = MagicMock()
        selected.scalar_one.return_value = existing
        mock_session.execute.side_effect = [MagicMock(), selected, MagicMock(), selected]
        correlation_id = uuid4()
        user_id = uuid4()

        first = await repository.create_asymmetric_feedback(
            correlation_id=correlation_id,
            user_id=user_id,
            feedback_type=ScoreFeedbackType.GOOD,
            request_id="request-123",
        )
        second = await repository.create_asymmetric_feedback(
            correlation_id=correlation_id,
            user_id=user_id,
            feedback_type=ScoreFeedbackType.TOO_LOW,
            request_id="request-123",
        )

        assert first is existing
        assert second is existing
        mock_session.add.assert_not_called()


class TestCreateManualAdjustment:
    """Tests for create_manual_adjustment method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session with synchronous add method."""
        session = create_mock_session()
        session.add = MagicMock()
        return session

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> FeedbackRepository:
        """Create repository with mock session."""
        return FeedbackRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_create_adjustment(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test creating a manual adjustment."""
        correlation_id = uuid4()
        user_id = uuid4()
        original_score = 0.75
        adjusted_score = 0.60
        reasoning = "Missing key skills that are required for this role"

        await repository.create_manual_adjustment(
            correlation_id=correlation_id,
            user_id=user_id,
            original_score=original_score,
            adjusted_score=adjusted_score,
            reasoning=reasoning,
        )

        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once()

        added_model = mock_session.add.call_args[0][0]
        assert added_model.correlation_id == correlation_id
        assert added_model.user_id == user_id
        assert added_model.original_score == pytest.approx(original_score)
        assert added_model.adjusted_score == pytest.approx(adjusted_score)
        assert added_model.reasoning == reasoning

    @pytest.mark.asyncio
    async def test_create_adjustment_full_range_low(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test creating adjustment with minimum score values."""
        await repository.create_manual_adjustment(
            correlation_id=uuid4(),
            user_id=uuid4(),
            original_score=0.0,
            adjusted_score=0.0,
            reasoning="Completely irrelevant listing",
        )

        added_model = mock_session.add.call_args[0][0]
        assert added_model.original_score == pytest.approx(0.0)
        assert added_model.adjusted_score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_create_adjustment_full_range_high(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test creating adjustment with maximum score values."""
        await repository.create_manual_adjustment(
            correlation_id=uuid4(),
            user_id=uuid4(),
            original_score=1.0,
            adjusted_score=1.0,
            reasoning="Perfect match for this position",
        )

        added_model = mock_session.add.call_args[0][0]
        assert added_model.original_score == pytest.approx(1.0)
        assert added_model.adjusted_score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_duplicate_request_returns_original_adjustment_without_adding_a_row(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Retrying one request ID cannot create a second manual adjustment."""
        existing = MagicMock()
        selected = MagicMock()
        selected.scalar_one.return_value = existing
        mock_session.execute.side_effect = [MagicMock(), selected, MagicMock(), selected]
        correlation_id = uuid4()
        user_id = uuid4()

        first = await repository.create_manual_adjustment(
            correlation_id=correlation_id,
            user_id=user_id,
            original_score=0.75,
            adjusted_score=0.25,
            reasoning="first",
            request_id="request-456",
        )
        second = await repository.create_manual_adjustment(
            correlation_id=correlation_id,
            user_id=user_id,
            original_score=0.10,
            adjusted_score=0.90,
            reasoning="retry with changed payload",
            request_id="request-456",
        )

        assert first is existing
        assert second is existing
        mock_session.add.assert_not_called()

    @pytest.mark.parametrize(
        ("field", "invalid_score"),
        [
            ("original_score", -0.01),
            ("original_score", 1.01),
            ("original_score", float("nan")),
            ("original_score", float("inf")),
            ("adjusted_score", -0.01),
            ("adjusted_score", 1.01),
            ("adjusted_score", float("nan")),
            ("adjusted_score", float("-inf")),
        ],
        ids=[
            "original-below-zero",
            "original-above-one",
            "original-nan",
            "original-infinite",
            "adjusted-below-zero",
            "adjusted-above-one",
            "adjusted-nan",
            "adjusted-infinite",
        ],
    )
    @pytest.mark.asyncio
    async def test_rejects_invalid_adjustment_scores_before_persistence(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
        field: str,
        invalid_score: float,
    ) -> None:
        """Manual adjustment scores must be finite probabilities."""
        scores = {"original_score": 0.5, "adjusted_score": 0.5}
        scores[field] = invalid_score

        with pytest.raises(ValueError, match=rf"{field} must be finite and between 0 and 1"):
            await repository.create_manual_adjustment(
                uuid4(),
                uuid4(),
                ManualAdjustmentCreate(
                    original_score=float(scores["original_score"]),
                    adjusted_score=float(scores["adjusted_score"]),
                    reasoning="invalid score",
                ),
            )

        mock_session.add.assert_not_called()


class TestGetAsymmetricFeedbackById:
    """Tests for get_asymmetric_feedback_by_id method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> FeedbackRepository:
        """Create repository with mock session."""
        return FeedbackRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_get_by_id_found(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_asymmetric_feedback_by_id returns feedback when found."""
        feedback_id = uuid4()
        mock_feedback = MagicMock()
        mock_feedback.id = feedback_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_feedback
        mock_session.execute.return_value = mock_result

        result = await repository.get_asymmetric_feedback_by_id(feedback_id)

        assert result is not None
        assert result.id == feedback_id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_asymmetric_feedback_by_id returns None when not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.get_asymmetric_feedback_by_id(uuid4())

        assert result is None


class TestGetManualAdjustmentById:
    """Tests for get_manual_adjustment_by_id method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> FeedbackRepository:
        """Create repository with mock session."""
        return FeedbackRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_get_by_id_found(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_manual_adjustment_by_id returns adjustment when found."""
        adjustment_id = uuid4()
        mock_adjustment = MagicMock()
        mock_adjustment.id = adjustment_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_adjustment
        mock_session.execute.return_value = mock_result

        result = await repository.get_manual_adjustment_by_id(adjustment_id)

        assert result is not None
        assert result.id == adjustment_id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_manual_adjustment_by_id returns None when not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.get_manual_adjustment_by_id(uuid4())

        assert result is None


class TestGetFeedbackForCorrelation:
    """Tests for get_feedback_for_correlation method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> FeedbackRepository:
        """Create repository with mock session."""
        return FeedbackRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_get_feedback_returns_list(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_feedback_for_correlation returns list."""
        correlation_id = uuid4()
        mock_feedback_list = [MagicMock(), MagicMock()]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_feedback_list
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        results = await repository.get_feedback_for_correlation(correlation_id)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_feedback_empty(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_feedback_for_correlation returns empty list when no feedback."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        results = await repository.get_feedback_for_correlation(uuid4())

        assert results == []


class TestGetAdjustmentsForCorrelation:
    """Tests for get_adjustments_for_correlation method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> FeedbackRepository:
        """Create repository with mock session."""
        return FeedbackRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_get_adjustments_returns_list(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_adjustments_for_correlation returns list."""
        correlation_id = uuid4()
        mock_adjustment_list = [MagicMock(), MagicMock(), MagicMock()]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_adjustment_list
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        results = await repository.get_adjustments_for_correlation(correlation_id)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_get_adjustments_empty(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_adjustments_for_correlation returns empty list when none exist."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        results = await repository.get_adjustments_for_correlation(uuid4())

        assert results == []


class TestGetUserFeedbackForCorrelation:
    """Tests for get_user_feedback_for_correlation method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> FeedbackRepository:
        """Create repository with mock session."""
        return FeedbackRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_get_user_feedback_found(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_user_feedback_for_correlation returns most recent feedback."""
        correlation_id = uuid4()
        user_id = uuid4()
        mock_feedback = MagicMock()
        mock_feedback.id = uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_feedback
        mock_session.execute.return_value = mock_result

        result = await repository.get_user_feedback_for_correlation(
            correlation_id=correlation_id,
            user_id=user_id,
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_get_user_feedback_not_found(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_user_feedback_for_correlation returns None when not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.get_user_feedback_for_correlation(
            correlation_id=uuid4(),
            user_id=uuid4(),
        )

        assert result is None


class TestCountFeedbackByType:
    """Tests for count_feedback_by_type method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> FeedbackRepository:
        """Create repository with mock session."""
        return FeedbackRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_count_feedback_with_data(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test count_feedback_by_type returns counts for each type."""
        mock_rows = [
            (ScoreFeedbackType.GOOD.name, 5),
            (ScoreFeedbackType.TOO_HIGH.name, 3),
            (ScoreFeedbackType.TOO_LOW.name, 2),
        ]
        mock_session.execute.return_value = iter(mock_rows)

        counts = await repository.count_feedback_by_type(uuid4())

        assert counts[ScoreFeedbackType.GOOD] == 5
        assert counts[ScoreFeedbackType.TOO_HIGH] == 3
        assert counts[ScoreFeedbackType.TOO_LOW] == 2

    @pytest.mark.asyncio
    async def test_count_feedback_empty(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test count_feedback_by_type returns zeros when no feedback."""
        mock_session.execute.return_value = iter([])

        counts = await repository.count_feedback_by_type(uuid4())

        assert counts[ScoreFeedbackType.GOOD] == 0
        assert counts[ScoreFeedbackType.TOO_HIGH] == 0
        assert counts[ScoreFeedbackType.TOO_LOW] == 0

    @pytest.mark.asyncio
    async def test_count_feedback_partial(
        self,
        repository: FeedbackRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test count_feedback_by_type with only some types present."""
        mock_rows = [
            (ScoreFeedbackType.GOOD.name, 10),
        ]
        mock_session.execute.return_value = iter(mock_rows)

        counts = await repository.count_feedback_by_type(uuid4())

        assert counts[ScoreFeedbackType.GOOD] == 10
        assert counts[ScoreFeedbackType.TOO_HIGH] == 0
        assert counts[ScoreFeedbackType.TOO_LOW] == 0

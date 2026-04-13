"""Deterministic tests for listing feedback quality scoring."""

from __future__ import annotations

from uuid import uuid4

import pytest
from job_correlation_evaluation_service.services.scoring.listing_quality import (
    ListingFeedbackAggregate,
    ListingQualityPredictor,
)


def _aggregate(good: int = 0, too_high: int = 0, too_low: int = 0) -> ListingFeedbackAggregate:
    return ListingFeedbackAggregate(
        listing_id=uuid4(),
        good_count=good,
        too_high_count=too_high,
        too_low_count=too_low,
    )


class TestListingFeedbackAggregate:
    """Feedback counts and derived quality signals are deterministic and bounded."""

    def test_total_feedback_and_ratios(self) -> None:
        aggregate = _aggregate(good=6, too_high=2, too_low=2)

        assert aggregate.total_feedback == 10
        assert aggregate.good_ratio == pytest.approx(0.6)
        assert aggregate.too_high_ratio == pytest.approx(0.2)
        assert aggregate.too_low_ratio == pytest.approx(0.2)

    def test_zero_feedback_is_neutral(self) -> None:
        aggregate = _aggregate()

        assert aggregate.total_feedback == 0
        assert aggregate.good_ratio == pytest.approx(0.5)
        assert aggregate.too_high_ratio == pytest.approx(0.0)
        assert aggregate.too_low_ratio == pytest.approx(0.0)
        assert aggregate.quality_signal == pytest.approx(0.5)

    def test_balanced_feedback_applies_declared_weights(self) -> None:
        aggregate = _aggregate(too_high=5, too_low=5)

        assert aggregate.quality_signal == pytest.approx(0.4)

    def test_imbalanced_high_feedback_lowers_signal(self) -> None:
        aggregate = _aggregate(good=1, too_high=9)

        assert aggregate.quality_signal < 0.5

    def test_imbalanced_low_feedback_raises_signal(self) -> None:
        aggregate = _aggregate(good=1, too_low=9)

        assert aggregate.quality_signal > 0.5

    @pytest.mark.parametrize(
        ("good", "too_high", "too_low"),
        [(0, 10_000, 0), (0, 0, 10_000), (10_000, 0, 0)],
    )
    def test_quality_signal_stays_within_bounds(self, good: int, too_high: int, too_low: int) -> None:
        signal = _aggregate(good, too_high, too_low).quality_signal

        assert 0.0 <= signal <= 1.0


class TestListingQualityPredictor:
    """The predictor delegates to the artifact-free aggregate signal."""

    def test_predict_is_deterministic(self) -> None:
        predictor = ListingQualityPredictor()
        aggregate = _aggregate(good=7, too_high=2, too_low=1)

        first = predictor.predict(aggregate)
        second = predictor.predict(aggregate)

        assert first == second == pytest.approx(0.44)

    def test_predict_cold_start_is_neutral(self) -> None:
        assert ListingQualityPredictor().predict_cold_start() == pytest.approx(0.5)

    def test_create_untrained_returns_predictor(self) -> None:
        predictor = ListingQualityPredictor.create_untrained()

        assert isinstance(predictor, ListingQualityPredictor)
        assert predictor.predict(_aggregate()) == pytest.approx(0.5)

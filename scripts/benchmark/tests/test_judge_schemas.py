"""Tests for judge evaluation Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_benchmark.schemas.judge import CATEGORY_NAMES, CategoryScore, PointwiseJudgment


def _make_category_score(score: int = 75) -> CategoryScore:
    return CategoryScore(score=score, reasoning="This is a detailed reasoning for this score value.")


def _make_pointwise_judgment(score: int = 75) -> PointwiseJudgment:
    category = _make_category_score(score)
    return PointwiseJudgment(
        inference_reasonableness=category,
        description_quality=category,
        downstream_usefulness=category,
        summary="Residual subjective quality was handled consistently.",
    )


class TestCategoryNames:
    """Tests for CATEGORY_NAMES constant."""

    def test_matches_pointwise_judgment_fields(self) -> None:
        judgment = _make_pointwise_judgment()
        assert tuple(judgment.category_scores.keys()) == CATEGORY_NAMES

    def test_has_three_residual_categories(self) -> None:
        assert len(CATEGORY_NAMES) == 3

    def test_is_immutable_tuple(self) -> None:
        assert isinstance(CATEGORY_NAMES, tuple)


class TestCategoryScore:
    """Tests for CategoryScore model."""

    def test_valid_score(self) -> None:
        cs = CategoryScore(score=85, reasoning="Good extraction with accurate data.")
        assert cs.score == 85

    def test_score_bounds_low(self) -> None:
        cs = CategoryScore(score=0, reasoning="Completely incorrect extraction output.")
        assert cs.score == 0

    def test_score_bounds_high(self) -> None:
        cs = CategoryScore(score=100, reasoning="Perfect extraction with no errors at all.")
        assert cs.score == 100

    def test_score_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CategoryScore(score=-1, reasoning="Invalid score below zero bound.")

    def test_score_above_100_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CategoryScore(score=101, reasoning="Invalid score above upper bound.")

    def test_reasoning_too_short(self) -> None:
        with pytest.raises(ValidationError):
            CategoryScore(score=50, reasoning="Short")


class TestPointwiseJudgment:
    """Tests for PointwiseJudgment model."""

    def test_category_scores_dict(self) -> None:
        judgment = _make_pointwise_judgment(score=80)
        scores = judgment.category_scores
        assert len(scores) == 3
        assert all(value == 80 for value in scores.values())

    def test_average_score(self) -> None:
        judgment = _make_pointwise_judgment(score=80)
        assert judgment.average_score == pytest.approx(80.0)

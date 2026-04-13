"""Contract tests for deterministic Stage 4 fit ranking."""

from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from job_correlation_evaluation_service.services.scoring.features.base import FactorName, FeatureComposition
from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import (
    DeterministicFinalStage,
    ScoredCandidate,
    _score_composition,
)
from job_correlation_evaluation_service.services.scoring.stages.llm_rerank import RerankCandidate
from nohiki.job.listing.v1 import ListingSnapshot


def _profile(**importance: int) -> MagicMock:
    profile = MagicMock()
    if importance:
        defaults = {
            "skill_match_importance": None,
            "location_importance": None,
            "work_arrangement_importance": None,
            "experience_importance": None,
            "salary_importance": None,
            "recency_importance": None,
        }
        defaults.update(importance)
        profile.feature_importance = SimpleNamespace(**defaults)
    else:
        profile.feature_importance = None
    return profile


def _composition(
    *,
    skills: float | None = None,
    location: float | None = None,
    work_arrangement: float | None = None,
    experience: float | None = None,
    salary: float | None = None,
    recency: float | None = None,
) -> FeatureComposition:
    factor_scores: dict[FactorName, float] = {}
    if skills is not None:
        factor_scores["skills"] = skills
    if location is not None:
        factor_scores["location"] = location
    if work_arrangement is not None:
        factor_scores["work_arrangement"] = work_arrangement
    if experience is not None:
        factor_scores["experience"] = experience
    if salary is not None:
        factor_scores["salary"] = salary
    if recency is not None:
        factor_scores["recency"] = recency
    return FeatureComposition(raw_features=np.array([0.25, math.nan], dtype=np.float32), factor_scores=factor_scores)


def _score(
    maxsim: float = 0.6,
    profile: MagicMock | None = None,
    *,
    skills: float | None = None,
    location: float | None = None,
    work_arrangement: float | None = None,
    experience: float | None = None,
    salary: float | None = None,
    recency: float | None = None,
) -> ScoredCandidate:
    composition = _composition(
        skills=skills,
        location=location,
        work_arrangement=work_arrangement,
        experience=experience,
        salary=salary,
        recency=recency,
    )
    return _score_composition("job", maxsim, 0.0, composition, profile or _profile())


class TestDeterministicFormula:
    def test_exact_formula_half_up_rounding_and_reconciliation(self) -> None:
        result = _score(0.5, skills=1.0, location=0.0)
        weight = 1 / 12
        expected = (0.5 + weight) / (1 + 2 * weight)

        assert result.rank_index == pytest.approx(expected)
        assert result.final_score == math.floor(100 * expected + 0.5)
        assert 100 * result.rank_index == pytest.approx(
            100 * result.maxsim_score + sum(item.contribution_points for item in result.factor_attributions),
            abs=1e-12,
        )
        assert result.feature_vector[0] == pytest.approx(0.25)
        assert math.isnan(result.feature_vector[1])

    @pytest.mark.parametrize(
        ("importance", "expected"),
        [(0, 0.5), (50, (0.5 + 1 / 12) / (1 + 1 / 12)), (100, (0.5 + 1 / 6) / (1 + 1 / 6))],
    )
    def test_importance_zero_neutral_and_full_boundaries(self, importance: int, expected: float) -> None:
        result = _score(0.5, _profile(skill_match_importance=importance), skills=1.0)

        assert result.rank_index == pytest.approx(expected)
        attribution = result.factor_attributions[0]
        assert attribution.importance == importance
        if importance == 0:
            assert attribution.contribution_points == 0.0

    def test_partial_importance_defaults_each_missing_field_to_fifty(self) -> None:
        result = _score(0.5, _profile(skill_match_importance=100), skills=1.0, location=1.0)

        assert [factor.importance for factor in result.factor_attributions] == [100, 50]

    def test_missing_factor_is_omitted_but_observed_zero_is_retained(self) -> None:
        missing = _score(0.7)
        observed_zero = _score(0.7, skills=0.0)

        assert missing.rank_index == pytest.approx(0.7)
        assert missing.factor_attributions == ()
        assert observed_zero.rank_index < missing.rank_index
        assert observed_zero.factor_attributions[0].compatibility == 0.0
        assert observed_zero.factor_attributions[0].contribution_points < 0.0

    @pytest.mark.parametrize("maxsim", [-3.0, 0.0, 1.0, 4.0])
    def test_finite_inputs_are_clamped_and_outputs_bounded(self, maxsim: float) -> None:
        result = _score(maxsim, skills=0.0, location=1.0)
        assert math.isfinite(result.rank_index)
        assert 0.0 <= result.rank_index <= 1.0
        assert 0 <= result.final_score <= 100

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
    def test_nonfinite_maxsim_is_rejected(self, value: float) -> None:
        with pytest.raises(ValueError, match="Non-finite MaxSim"):
            _score(value)

    @pytest.mark.parametrize("value", [math.nan, math.inf, -0.01, 1.01])
    def test_invalid_factor_score_is_rejected(self, value: float) -> None:
        with pytest.raises(ValueError, match="Invalid skills compatibility"):
            _score(0.5, skills=value)

    @pytest.mark.parametrize("importance", [-1, 101])
    def test_invalid_importance_is_rejected(self, importance: int) -> None:
        with pytest.raises(ValueError, match="between 0 and 100"):
            _score(0.5, _profile(skill_match_importance=importance), skills=1.0)


class TestDeterministicStage:
    def test_batch_sorts_unrounded_index_then_maxsim_then_entity_id(self) -> None:
        composer = MagicMock()
        factor_by_id = {"z": 0.5, "b": 0.5, "a": 0.5, "high-factor": 0.5004}
        composer.extract.side_effect = lambda listing, _profile, _scores: _composition(skills=factor_by_id[listing.id])
        stage = DeterministicFinalStage(composer)
        profile = _profile()
        listings = {
            "z": ListingSnapshot(id="z"),
            "b": ListingSnapshot(id="b"),
            "a": ListingSnapshot(id="a"),
            "high-factor": ListingSnapshot(id="high-factor"),
        }
        candidates = [
            RerankCandidate(entity_id="z", maxsim_score=0.5, rerank_score=0.0, payload={}),
            RerankCandidate(entity_id="b", maxsim_score=0.5, rerank_score=0.0, payload={}),
            RerankCandidate(entity_id="a", maxsim_score=0.5, rerank_score=0.0, payload={}),
            RerankCandidate(entity_id="high-factor", maxsim_score=0.5, rerank_score=0.0, payload={}),
        ]

        ranked = stage.score_batch(list(reversed(candidates)), listings, profile)

        assert [item.entity_id for item in ranked] == ["high-factor", "a", "b", "z"]
        assert len({item.final_score for item in ranked}) == 1

    def test_equal_rank_uses_higher_maxsim_before_entity_id(self) -> None:
        composer = MagicMock()
        composer.extract.side_effect = [
            _composition(skills=1.0),
            _composition(skills=0.0),
        ]
        stage = DeterministicFinalStage(composer)
        # Both rank to 7/13; the second candidate wins on its higher semantic anchor.
        candidates = [
            RerankCandidate(entity_id="a", maxsim_score=0.5, rerank_score=0.0, payload={}),
            RerankCandidate(entity_id="z", maxsim_score=7 / 12, rerank_score=0.0, payload={}),
        ]

        ranked = stage.score_batch(candidates, {"a": ListingSnapshot(id="a"), "z": ListingSnapshot(id="z")}, _profile())

        assert ranked[0].entity_id == "z"
        assert ranked[0].rank_index == pytest.approx(ranked[1].rank_index)

    def test_empty_batch_and_missing_listing(self) -> None:
        stage = DeterministicFinalStage(MagicMock())
        candidate = RerankCandidate(entity_id="missing", maxsim_score=0.5, rerank_score=0.0, payload={})

        assert stage.score_batch([], {}, _profile()) == []
        assert stage.score_batch([candidate], {}, _profile()) == []

    def test_single_and_inline_paths_are_identical(self) -> None:
        composer = MagicMock(return_value=None)
        composer.extract.return_value = _composition(skills=0.8)
        stage = DeterministicFinalStage(composer)
        listing = ListingSnapshot(id="job")
        profile = _profile()
        candidate = RerankCandidate(entity_id="job", maxsim_score=0.7, rerank_score=0.0, payload={})

        single = stage.score_single(candidate, listing, profile)
        inline = stage.score_with_inline_maxsim(listing, profile, 0.7)
        assert single.rank_index == inline.rank_index
        assert single.final_score == inline.final_score
        assert single.factor_attributions == inline.factor_attributions
        np.testing.assert_equal(single.feature_vector, inline.feature_vector)

    def test_create_does_not_read_model_or_calibrator_files(self) -> None:
        with patch("builtins.open", side_effect=AssertionError("artifact read attempted")):
            stage = DeterministicFinalStage.create()

        assert isinstance(stage, DeterministicFinalStage)

    def test_contract_contains_no_probability_or_confidence_fields(self) -> None:
        result = _score(0.5, skills=1.0)
        public_fields = set(result.__dataclass_fields__)

        assert "calibrated_probability" not in public_fields
        assert "confidence" not in public_fields
        assert public_fields >= {"rank_index", "final_score", "factor_attributions"}

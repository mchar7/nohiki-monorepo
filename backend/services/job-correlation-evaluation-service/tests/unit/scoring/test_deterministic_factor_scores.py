"""Availability and boundary contracts for deterministic fit factors."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from job_correlation_evaluation_service.services.scoring.constants import FEATURE_COUNT
from job_correlation_evaluation_service.services.scoring.features import FeatureExtractionContext, PipelineScores
from job_correlation_evaluation_service.services.scoring.features.groups.experience import ExperienceFeatureGroup
from job_correlation_evaluation_service.services.scoring.features.groups.job_metadata import JobMetadataFeatureGroup
from job_correlation_evaluation_service.services.scoring.features.groups.location import LocationFeatureGroup
from job_correlation_evaluation_service.services.scoring.features.groups.salary import SalaryFeatureGroup
from job_correlation_evaluation_service.services.scoring.features.groups.skill import SkillFeatureGroup
from job_correlation_evaluation_service.services.scoring.features.groups.work_arrangement import (
    WorkArrangementFeatureGroup,
)
from job_correlation_evaluation_service.services.scoring.features.location_scorer import (
    LocationMatchResult,
    LocationScenario,
)
from nohiki.common.v1 import (
    Compensation,
    CompensationBound,
    CurrencyCode,
    ExperiencePreference,
    Location,
    MonetaryAmount,
    PaymentFrequency,
    SalaryPreference,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot


def _context(job: ListingSnapshot, profile: SearchPrefSnapshot) -> FeatureExtractionContext:
    return FeatureExtractionContext(
        job=job,
        profile=profile,
        pipeline_scores=PipelineScores(maxsim_score=0.5, rerank_score=0.0),
    )


def _features() -> np.ndarray:
    return np.full(FEATURE_COUNT, math.nan, dtype=np.float32)


def _money(units: int, currency: CurrencyCode = CurrencyCode.USD) -> MonetaryAmount:
    return MonetaryAmount(minor_units=units, currency=currency)


class TestSkillsFactor:
    @pytest.mark.parametrize(
        ("available", "score", "expected"), [(False, math.nan, None), (True, 0.0, 0.0), (True, 1.0, 1.0)]
    )
    def test_missing_is_omitted_observed_boundaries_are_retained(
        self, available: int, score: float, expected: float | None
    ) -> None:
        calculator = MagicMock()
        calculator.compute.return_value = SimpleNamespace(
            matched_skill_count=0,
            missing_skill_ids=[] if score == 1.0 else ["python"],
            total_job_required_skills=1 if available else 0,
            proficiency_weighted_score=score,
            provenance_weighted_score=score,
            expanded_user_skill_ids=set(),
            total_user_skills=0,
            has_skill_data=available,
            skill_match_quality=score,
        )
        context = _context(ListingSnapshot(skill_requirements=[]), SearchPrefSnapshot(user_skills=[]))

        SkillFeatureGroup(calculator).extract(_features(), context)

        assert context.factor_scores.get("skills") == expected


class TestLocationFactor:
    @pytest.mark.parametrize(
        ("scoreable", "score", "expected"), [(False, 0.0, None), (True, 0.0, 0.0), (True, 1.0, 1.0)]
    )
    def test_only_scoreable_results_are_available(self, scoreable: int, score: float, expected: float | None) -> None:
        scorer = MagicMock()
        scorer.score.return_value = LocationMatchResult(
            score=score,
            is_scoreable=bool(scoreable),
            scenario=LocationScenario.LOCAL_COMMUTE,
            distance_km=10.0,
            is_same_city=score == 1.0,
            fallback_reason=None if scoreable else "insufficient evidence",
        )
        context = _context(
            ListingSnapshot(location=Location(), work_arrangement=WorkArrangement.ON_SITE),
            SearchPrefSnapshot(
                physical_locations=[Location()],
                remote_locations=[],
                work_arrangements=[WorkArrangement.ON_SITE],
                open_to_relocation=False,
            ),
        )

        LocationFeatureGroup(scorer).extract(_features(), context)

        assert context.factor_scores.get("location") == expected


class TestWorkArrangementFactor:
    @pytest.mark.parametrize(
        ("job_value", "preferences", "expected"),
        [
            (WorkArrangement.UNSPECIFIED, [WorkArrangement.REMOTE], None),
            (WorkArrangement.REMOTE, [], None),
            (WorkArrangement.ON_SITE, [WorkArrangement.REMOTE], 0.0),
            (WorkArrangement.REMOTE, [WorkArrangement.REMOTE], 1.0),
        ],
    )
    def test_binary_match_and_missingness(
        self, job_value: WorkArrangement, preferences: list[WorkArrangement], expected: float | None
    ) -> None:
        context = _context(
            ListingSnapshot(work_arrangement=job_value), SearchPrefSnapshot(work_arrangements=preferences)
        )

        WorkArrangementFeatureGroup().extract(_features(), context)

        assert context.factor_scores.get("work_arrangement") == expected


class TestExperienceFactor:
    @pytest.mark.parametrize(
        ("years", "minimum", "maximum", "expected"),
        [(3, 3, 5, 1.0), (5, 3, 5, 1.0), (0, 5, 8, 0.3), (20, 3, 5, 0.5)],
    )
    def test_years_boundaries_and_penalty_floors(self, years: int, minimum: int, maximum: int, expected: float) -> None:
        context = _context(
            ListingSnapshot(
                experience_years_min=minimum, experience_years_max=maximum, seniority_level=SeniorityLevel.UNSPECIFIED
            ),
            SearchPrefSnapshot(experience_preference=ExperiencePreference(experience_years=years, seniority_levels=[])),
        )

        ExperienceFeatureGroup().extract(_features(), context)

        assert context.factor_scores["experience"] == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("preferred", "expected"),
        [
            ([SeniorityLevel.SENIOR], 1.0),
            ([SeniorityLevel.MID], 0.8),
            ([SeniorityLevel.ENTRY], 0.5),
            ([SeniorityLevel.INTERN], 0.2),
            ([SeniorityLevel.INTERN, SeniorityLevel.SENIOR], 1.0),
        ],
    )
    def test_seniority_distance_uses_best_preference(self, preferred: list[SeniorityLevel], expected: float) -> None:
        context = _context(
            ListingSnapshot(
                experience_years_min=None, experience_years_max=None, seniority_level=SeniorityLevel.SENIOR
            ),
            SearchPrefSnapshot(
                experience_preference=ExperiencePreference(experience_years=None, seniority_levels=preferred)
            ),
        )

        ExperienceFeatureGroup().extract(_features(), context)

        assert context.factor_scores["experience"] == pytest.approx(expected)

    def test_missing_both_subfactors_is_omitted(self) -> None:
        context = _context(
            ListingSnapshot(
                experience_years_min=None, experience_years_max=None, seniority_level=SeniorityLevel.UNSPECIFIED
            ),
            SearchPrefSnapshot(experience_preference=None),
        )
        ExperienceFeatureGroup().extract(_features(), context)
        assert "experience" not in context.factor_scores


class TestSalaryFactor:
    @pytest.mark.parametrize(
        ("job_units", "desired_units", "expected"), [(50, 100, 0.5), (100, 100, 1.0), (150, 100, 1.0)]
    )
    def test_same_currency_ratio_is_bounded(self, job_units: int, desired_units: int, expected: float) -> None:
        context = _context(
            ListingSnapshot(
                compensation=Compensation(
                    fixed_amount=CompensationBound(amount=_money(job_units)),
                    min_amount=None,
                    max_amount=None,
                    frequency=PaymentFrequency.ANNUALLY,
                )
            ),
            SearchPrefSnapshot(
                salary_preference=SalaryPreference(min_salary=None, target_salary=_money(desired_units))
            ),
        )

        SalaryFeatureGroup().extract(_features(), context)

        assert context.factor_scores["salary"] == pytest.approx(expected)

    def test_currency_mismatch_is_omitted(self) -> None:
        compensation = Compensation(
            fixed_amount=CompensationBound(amount=_money(100, CurrencyCode.USD)),
            min_amount=None,
            max_amount=None,
            frequency=PaymentFrequency.ANNUALLY,
        )
        profile = SearchPrefSnapshot(
            salary_preference=SalaryPreference(min_salary=None, target_salary=_money(100, CurrencyCode.CAD))
        )
        context = _context(ListingSnapshot(compensation=compensation), profile)

        SalaryFeatureGroup().extract(_features(), context)

        assert "salary" not in context.factor_scores


class TestRecencyFactor:
    @pytest.mark.parametrize(
        ("age_hours", "expected"), [(0.0, 1.0), (24.0 * 15, 0.5), (24.0 * 30, 0.0), (24.0 * 40, 0.0)]
    )
    def test_linear_boundaries(self, age_hours: float, expected: float) -> None:
        context = _context(ListingSnapshot(posted_at=datetime.now(UTC)), SearchPrefSnapshot())
        with patch(
            "job_correlation_evaluation_service.services.scoring.features.groups.job_metadata._compute_job_age_hours",
            return_value=age_hours,
        ):
            JobMetadataFeatureGroup().extract(_features(), context)

        assert context.factor_scores["recency"] == pytest.approx(expected)

    def test_missing_timestamp_is_omitted(self) -> None:
        context = _context(ListingSnapshot(posted_at=None), SearchPrefSnapshot())
        JobMetadataFeatureGroup().extract(_features(), context)
        assert "recency" not in context.factor_scores

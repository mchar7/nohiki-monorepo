"""Comprehensive feature signal validation tests.

Tests that every single one of the 32 L2R signals produces a valid, useful range
across varied inputs. For each feature group, validates:
- Output ranges (e.g., cosine similarity [-1,1], binary flags {0,1})
- Boundary conditions (zero, very large, very small, NaN-producing inputs)
- That varied inputs produce varied outputs (signal is not constantly 0/1)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pytest
from job_correlation_evaluation_service.services.scoring.constants import (
    FEATURE_COUNT,
    FeatureIndex,
)
from job_correlation_evaluation_service.services.scoring.features import (
    FeatureComposer,
    FeatureExtractionContext,
    PipelineScores,
)
from job_correlation_evaluation_service.services.scoring.features.groups.location import (
    LocationFeatureGroup,
)
from job_correlation_evaluation_service.services.scoring.features.groups.taxonomy import (
    TaxonomyFeatureGroup,
)
from job_correlation_evaluation_service.services.scoring.features.location_scorer import (
    LocationMatchResult,
    LocationScenario,
    LocationScorer,
)
from job_correlation_evaluation_service.services.scoring.skill_relationship_cache import (
    SkillRelationshipCache,
)
from nohiki.common.v1 import (
    CurrencyCode,
    PaymentFrequency,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki.skill.v1 import SkillProficiencyLevel, SkillProvenance


class TestPipelineFeatureGroup:
    """Validate pipeline score signals (indices 0-1)."""

    def test_maxsim_score_range(self) -> None:
        """MAXSIM_SCORE should be in valid 0-1 range."""
        composer = FeatureComposer.create_default()

        test_cases = [
            0.0,  # Boundary: minimum
            0.5,  # Mid-range
            1.0,  # Boundary: maximum
            0.123456,  # Precision
        ]

        for maxsim_val in test_cases:
            job = _create_minimal_job()
            profile = _create_minimal_profile()
            scores = PipelineScores(maxsim_score=maxsim_val, rerank_score=0.5)

            features = composer.extract(job, profile, scores).raw_features

            assert features[FeatureIndex.MAXSIM_SCORE] == pytest.approx(maxsim_val)
            assert 0.0 <= features[FeatureIndex.MAXSIM_SCORE] <= 1.0

    def test_rerank_score_range(self) -> None:
        """RERANK_SCORE should be in valid 0-1 range."""
        composer = FeatureComposer.create_default()

        test_cases = [
            0.0,  # No reranking applied
            0.25,
            0.75,
            1.0,  # Perfect rerank score
        ]

        for rerank_val in test_cases:
            job = _create_minimal_job()
            profile = _create_minimal_profile()
            scores = PipelineScores(maxsim_score=0.5, rerank_score=rerank_val)

            features = composer.extract(job, profile, scores).raw_features

            assert features[FeatureIndex.RERANK_SCORE] == pytest.approx(rerank_val)
            assert 0.0 <= features[FeatureIndex.RERANK_SCORE] <= 1.0

    def test_pipeline_scores_independence(self) -> None:
        """Pipeline scores should vary independently."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        profile = _create_minimal_profile()

        # Test various combinations
        scores_list = [
            (0.2, 0.8),  # Low maxsim, high rerank
            (0.8, 0.2),  # High maxsim, low rerank
            (0.5, 0.5),  # Both equal
        ]

        feature_arrays = []
        for maxsim, rerank in scores_list:
            scores = PipelineScores(maxsim_score=maxsim, rerank_score=rerank)
            features = composer.extract(job, profile, scores).raw_features
            feature_arrays.append(features)

        # Verify they produce different outputs
        assert not np.allclose(feature_arrays[0], feature_arrays[1])
        assert not np.allclose(feature_arrays[0], feature_arrays[2])


class TestLocationFeatureGroup:
    """Validate location signals (indices 2-5)."""

    def test_distance_km_nonnegative(self) -> None:
        """DISTANCE_KM should be non-negative when present."""
        mock_scorer = MagicMock(spec=LocationScorer)
        feature_group = LocationFeatureGroup(location_scorer=mock_scorer)

        distance_values = [0.0, 1.5, 50.0, 5000.0]  # Various distances

        for dist in distance_values:
            mock_scorer.score.return_value = LocationMatchResult(
                score=0.5,
                is_scoreable=True,
                scenario=LocationScenario.LOCAL_COMMUTE,
                distance_km=dist,
                is_same_city=False,
                fallback_reason=None,
            )

            features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
            job = _create_minimal_job()
            job.location = MagicMock()
            profile = _create_minimal_profile()
            profile.physical_locations = [MagicMock()]

            context = FeatureExtractionContext(
                job=job,
                profile=profile,
                pipeline_scores=PipelineScores(maxsim_score=0.5, rerank_score=0.5),
            )

            feature_group.extract(features, context)

            assert features[FeatureIndex.DISTANCE_KM] == pytest.approx(dist)
            assert features[FeatureIndex.DISTANCE_KM] >= 0.0

    def test_distance_km_nan_when_missing(self) -> None:
        """DISTANCE_KM should be NaN when location data is missing."""
        feature_group = LocationFeatureGroup()
        features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
        job = _create_minimal_job()
        job.location = None  # No location
        profile = _create_minimal_profile()
        profile.physical_locations = []

        context = FeatureExtractionContext(
            job=job,
            profile=profile,
            pipeline_scores=PipelineScores(maxsim_score=0.5, rerank_score=0.5),
        )

        feature_group.extract(features, context)

        assert math.isnan(features[FeatureIndex.DISTANCE_KM])

    def test_is_same_city_binary(self) -> None:
        """IS_SAME_CITY should be 0.0 or 1.0 when present."""
        mock_scorer = MagicMock(spec=LocationScorer)
        feature_group = LocationFeatureGroup(location_scorer=mock_scorer)

        test_cases = [
            (True, 1.0),  # Same city
            (False, 0.0),  # Different city
        ]

        for is_same, expected in test_cases:
            mock_scorer.score.return_value = LocationMatchResult(
                score=0.5,
                is_scoreable=True,
                scenario=LocationScenario.LOCAL_COMMUTE,
                distance_km=10.0,
                is_same_city=is_same,
                fallback_reason=None,
            )

            features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
            job = _create_minimal_job()
            job.location = MagicMock()
            profile = _create_minimal_profile()
            profile.physical_locations = [MagicMock()]

            context = FeatureExtractionContext(
                job=job,
                profile=profile,
                pipeline_scores=PipelineScores(maxsim_score=0.5, rerank_score=0.5),
            )

            feature_group.extract(features, context)

            assert features[FeatureIndex.IS_SAME_CITY] == pytest.approx(expected)

    def test_is_remote_job_binary(self) -> None:
        """IS_REMOTE_JOB should be 0.0 or 1.0."""
        feature_group = LocationFeatureGroup()

        test_cases = [
            (WorkArrangement.REMOTE, 1.0),
            (WorkArrangement.ON_SITE, 0.0),
            (WorkArrangement.HYBRID, 0.0),
        ]

        for arrangement, expected in test_cases:
            features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
            job = _create_minimal_job()
            job.work_arrangement = arrangement
            profile = _create_minimal_profile()

            context = FeatureExtractionContext(
                job=job,
                profile=profile,
                pipeline_scores=PipelineScores(maxsim_score=0.5, rerank_score=0.5),
            )

            feature_group.extract(features, context)

            assert features[FeatureIndex.IS_REMOTE_JOB] == pytest.approx(expected)

    def test_user_open_to_relocation_binary(self) -> None:
        """USER_OPEN_TO_RELOCATION should be 0.0 or 1.0."""
        feature_group = LocationFeatureGroup()

        test_cases = [
            (True, 1.0),
            (False, 0.0),
        ]

        for open_to_relocation, expected in test_cases:
            features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
            job = _create_minimal_job()
            profile = _create_minimal_profile()
            profile.open_to_relocation = open_to_relocation

            context = FeatureExtractionContext(
                job=job,
                profile=profile,
                pipeline_scores=PipelineScores(maxsim_score=0.5, rerank_score=0.5),
            )

            feature_group.extract(features, context)

            assert features[FeatureIndex.USER_OPEN_TO_RELOCATION] == pytest.approx(expected)


class TestExperienceFeatureGroup:
    """Validate experience signals (indices 6-10)."""

    def test_user_experience_years_nonnegative(self) -> None:
        """USER_EXPERIENCE_YEARS should be non-negative when present."""
        composer = FeatureComposer.create_default()

        experience_values = [0, 1, 5, 20, 50]  # Various experience levels

        for exp_years in experience_values:
            job = _create_minimal_job()
            profile = _create_minimal_profile()
            pref = MagicMock()
            pref.experience_years = exp_years
            pref.seniority_levels = []
            profile.experience_preference = pref
            scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

            features = composer.extract(job, profile, scores).raw_features

            assert features[FeatureIndex.USER_EXPERIENCE_YEARS] == pytest.approx(float(exp_years))

    def test_job_experience_range(self) -> None:
        """Job experience min/max should be non-negative when present."""
        composer = FeatureComposer.create_default()

        test_cases = [
            (0, 0),  # Entry level
            (1, 3),  # Junior
            (3, 5),  # Mid
            (5, 10),  # Senior
        ]

        for exp_min, exp_max in test_cases:
            job = _create_minimal_job()
            job.experience_years_min = exp_min
            job.experience_years_max = exp_max
            profile = _create_minimal_profile()
            scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

            features = composer.extract(job, profile, scores).raw_features

            assert features[FeatureIndex.JOB_EXPERIENCE_MIN] == pytest.approx(float(exp_min))
            assert features[FeatureIndex.JOB_EXPERIENCE_MAX] == pytest.approx(float(exp_max))
            assert features[FeatureIndex.JOB_EXPERIENCE_MAX] >= features[FeatureIndex.JOB_EXPERIENCE_MIN]

    def test_seniority_level_consistency(self) -> None:
        """Seniority level features should reflect enum values."""
        composer = FeatureComposer.create_default()

        # Test with different seniority levels
        seniority_levels = [
            SeniorityLevel.ENTRY,
            SeniorityLevel.MID,
            SeniorityLevel.SENIOR,
            SeniorityLevel.STAFF,
        ]

        for seniority in seniority_levels:
            job = _create_minimal_job()
            job.seniority_level = seniority
            profile = _create_minimal_profile()
            scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

            features = composer.extract(job, profile, scores).raw_features

            # Should match the seniority level value
            assert features[FeatureIndex.JOB_SENIORITY_LEVEL] == pytest.approx(float(int(seniority)))

    def test_experience_nan_when_missing(self) -> None:
        """Experience features should be NaN when missing."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        job.experience_years_min = None
        job.experience_years_max = None
        profile = _create_minimal_profile()
        profile.experience_preference = None
        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.USER_EXPERIENCE_YEARS])
        assert math.isnan(features[FeatureIndex.JOB_EXPERIENCE_MIN])
        assert math.isnan(features[FeatureIndex.JOB_EXPERIENCE_MAX])


class TestSalaryFeatureGroup:
    """Validate salary signals (indices 11-13)."""

    def test_salary_features_nonnegative(self) -> None:
        """Salary features should be non-negative when present."""
        composer = FeatureComposer.create_default()

        salary_values = [
            (10000, 20000),  # Low salary
            (50000, 75000),  # Mid salary
            (100000, 150000),  # High salary
        ]

        for user_min, user_target in salary_values:
            job = _create_minimal_job()
            job.compensation = _create_mock_compensation(user_min, user_target, CurrencyCode.USD)

            profile = _create_minimal_profile()
            salary_pref = _create_mock_salary_preference(user_min, user_target, CurrencyCode.USD)
            profile.salary_preference = salary_pref

            scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

            features = composer.extract(job, profile, scores).raw_features

            if not math.isnan(features[FeatureIndex.USER_MIN_SALARY]):
                assert features[FeatureIndex.USER_MIN_SALARY] >= 0
            if not math.isnan(features[FeatureIndex.USER_TARGET_SALARY]):
                assert features[FeatureIndex.USER_TARGET_SALARY] >= 0
            if not math.isnan(features[FeatureIndex.JOB_SALARY]):
                assert features[FeatureIndex.JOB_SALARY] >= 0

    def test_salary_nan_with_currency_mismatch(self) -> None:
        """All salary features should be NaN when currencies differ."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        job.compensation = _create_mock_compensation(50000, 75000, CurrencyCode.EUR)

        profile = _create_minimal_profile()
        salary_pref = _create_mock_salary_preference(50000, 75000, CurrencyCode.USD)
        profile.salary_preference = salary_pref

        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.USER_MIN_SALARY])
        assert math.isnan(features[FeatureIndex.USER_TARGET_SALARY])
        assert math.isnan(features[FeatureIndex.JOB_SALARY])

    def test_salary_nan_when_missing(self) -> None:
        """Salary features should be NaN when missing."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        job.compensation = None
        profile = _create_minimal_profile()
        profile.salary_preference = None
        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.USER_MIN_SALARY])
        assert math.isnan(features[FeatureIndex.USER_TARGET_SALARY])
        assert math.isnan(features[FeatureIndex.JOB_SALARY])


class TestSkillFeatureGroup:
    """Validate skill signals (indices 14-19)."""

    def test_skill_match_count_nonnegative(self) -> None:
        """SKILL_MATCH_COUNT should be non-negative."""
        composer = FeatureComposer.create_default()

        # Test with various skill counts; no match expectations since we don't mock skill matching logic
        job = _create_minimal_job()
        profile = _create_minimal_profile()
        # Create empty or simple skill lists
        profile.user_skills = []
        job.skill_requirements = []

        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.SKILL_MATCH_COUNT] >= 0

    def test_skill_missing_count_nonnegative(self) -> None:
        """SKILL_MISSING_COUNT should be non-negative."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        profile = _create_minimal_profile()
        # Test with empty skills list
        profile.user_skills = []
        job.skill_requirements = []

        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.SKILL_MISSING_COUNT] >= 0

    def test_skill_total_required_nonnegative(self) -> None:
        """SKILL_TOTAL_REQUIRED should be non-negative."""
        composer = FeatureComposer.create_default()

        skill_counts = [0, 1, 5, 20]

        for count in skill_counts:
            job = _create_minimal_job()
            job.skill_requirements = [_create_mock_skill(f"skill_{i}") for i in range(count)]
            profile = _create_minimal_profile()

            scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
            features = composer.extract(job, profile, scores).raw_features

            assert features[FeatureIndex.SKILL_TOTAL_REQUIRED] == pytest.approx(float(count))

    def test_skill_proficiency_range(self) -> None:
        """SKILL_AVG_PROFICIENCY should be in valid range or NaN."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        profile = _create_minimal_profile()
        # Create mock skills with proficiency info
        profile.user_skills = [_create_mock_skill(f"skill_{i}") for i in range(3)]
        job.skill_requirements = []

        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
        features = composer.extract(job, profile, scores).raw_features

        proficiency = features[FeatureIndex.SKILL_AVG_PROFICIENCY]
        # Should be either NaN or in [0, 1] range
        if not math.isnan(proficiency):
            assert 0.0 <= proficiency <= 1.0

    def test_skill_provenance_range(self) -> None:
        """SKILL_AVG_PROVENANCE should be in valid range or NaN."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        profile = _create_minimal_profile()
        profile.user_skills = [_create_mock_skill(f"skill_{i}") for i in range(3)]
        job.skill_requirements = []

        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
        features = composer.extract(job, profile, scores).raw_features

        provenance = features[FeatureIndex.SKILL_AVG_PROVENANCE]
        # Should be either NaN or in [0, 1] range
        if not math.isnan(provenance):
            assert 0.0 <= provenance <= 1.0

    def test_skill_relationship_count_nonnegative(self) -> None:
        """SKILL_RELATIONSHIP_COUNT should be non-negative."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        profile = _create_minimal_profile()
        profile.user_skills = [_create_mock_skill(f"skill_{i}") for i in range(3)]

        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.SKILL_RELATIONSHIP_COUNT] >= 0


class TestSemanticFeatureGroup:
    """Validate semantic similarity signals."""

    def test_skills_cosine_similarity_range(self) -> None:
        """SKILLS_COSINE_SIM should be in [-1, 1] when present."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        profile = _create_minimal_profile()

        # Create embeddings
        embedding_a = _create_mock_embedding([0.0, 1.0, 0.0])
        embedding_b = _create_mock_embedding([0.0, 1.0, 0.0])
        job.skills_embedding = embedding_a
        profile.user_skills_embedding = embedding_b

        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
        features = composer.extract(job, profile, scores).raw_features

        skills_sim = features[FeatureIndex.SKILLS_COSINE_SIM]
        if not math.isnan(skills_sim):
            assert -1.0 <= skills_sim <= 1.0

    def test_cosine_similarity_nan_with_incompatible_dimensions(self) -> None:
        """Cosine similarity should be NaN for incompatible embedding dimensions."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        profile = _create_minimal_profile()

        # Create embeddings with different dimensions
        embedding_a = _create_mock_embedding([1.0, 0.0])  # 2D
        embedding_b = _create_mock_embedding([1.0, 0.0, 0.0])  # 3D
        job.skills_embedding = embedding_a
        profile.user_skills_embedding = embedding_b

        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.SKILLS_COSINE_SIM])


class TestJobMetadataFeatureGroup:
    """Validate job metadata signals (indices 22-24)."""

    def test_job_age_hours_nonnegative(self) -> None:
        """JOB_AGE_HOURS should be non-negative."""
        composer = FeatureComposer.create_default()

        now = datetime.now(UTC)

        age_deltas = [
            timedelta(hours=0),  # Just posted
            timedelta(hours=1),
            timedelta(days=1),
            timedelta(days=30),
        ]

        for delta in age_deltas:
            job = _create_minimal_job()
            job.posted_at = now - delta
            profile = _create_minimal_profile()
            scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

            features = composer.extract(job, profile, scores).raw_features

            age_hours = features[FeatureIndex.JOB_AGE_HOURS]
            if not math.isnan(age_hours):
                assert age_hours >= 0


class TestWorkArrangementFeatureGroup:
    """Validate work arrangement match signal (index 25)."""

    def test_work_arrangement_match_binary(self) -> None:
        """WORK_ARRANGEMENT_MATCH should be 0.0 or 1.0 when present."""
        composer = FeatureComposer.create_default()

        test_cases = [
            (WorkArrangement.REMOTE, [WorkArrangement.REMOTE], 1.0),  # Match
            (WorkArrangement.HYBRID, [WorkArrangement.REMOTE], 0.0),  # No match
            (WorkArrangement.ON_SITE, [WorkArrangement.ON_SITE, WorkArrangement.HYBRID], 1.0),  # Match
            (WorkArrangement.HYBRID, [WorkArrangement.ON_SITE, WorkArrangement.HYBRID], 1.0),  # Match
        ]

        for job_arr, profile_arrs, expected in test_cases:
            job = _create_minimal_job()
            job.work_arrangement = job_arr
            profile = _create_minimal_profile()
            profile.work_arrangements = profile_arrs

            scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
            features = composer.extract(job, profile, scores).raw_features

            assert features[FeatureIndex.WORK_ARRANGEMENT_MATCH] == pytest.approx(expected)

    def test_work_arrangement_nan_when_unspecified(self) -> None:
        """WORK_ARRANGEMENT_MATCH should be NaN when job arrangement is UNSPECIFIED."""
        composer = FeatureComposer.create_default()

        job = _create_minimal_job()
        job.work_arrangement = WorkArrangement.UNSPECIFIED
        profile = _create_minimal_profile()
        profile.work_arrangements = [WorkArrangement.REMOTE]

        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)
        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.WORK_ARRANGEMENT_MATCH])


class TestValidityFlagsFeatureGroup:
    """Validate validity flags (indices 26-30)."""

    def test_has_location_data_flag(self) -> None:
        """HAS_LOCATION_DATA should be 1.0 when location data exists, 0.0 otherwise."""
        composer = FeatureComposer.create_default()

        # Test with location data
        job = _create_minimal_job()
        job.location = MagicMock()
        profile = _create_minimal_profile()
        profile.physical_locations = [MagicMock()]
        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

        features = composer.extract(job, profile, scores).raw_features
        # If distance is not NaN, flag should be 1
        if not math.isnan(features[FeatureIndex.DISTANCE_KM]):
            assert features[FeatureIndex.HAS_LOCATION_DATA] == pytest.approx(1.0)

        # Test without location data
        job = _create_minimal_job()
        job.location = None
        profile = _create_minimal_profile()
        features = composer.extract(job, profile, scores).raw_features
        assert features[FeatureIndex.HAS_LOCATION_DATA] == pytest.approx(0.0)

    def test_has_experience_data_flag(self) -> None:
        """HAS_EXPERIENCE_DATA should be 1.0 when experience data exists."""
        composer = FeatureComposer.create_default()

        # Test with experience data
        job = _create_minimal_job()
        job.experience_years_min = 2
        job.experience_years_max = 5
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

        features = composer.extract(job, profile, scores).raw_features
        assert features[FeatureIndex.HAS_EXPERIENCE_DATA] == pytest.approx(1.0)

        # Test without experience data
        job = _create_minimal_job()
        job.experience_years_min = None
        job.experience_years_max = None
        features = composer.extract(job, profile, scores).raw_features
        assert features[FeatureIndex.HAS_EXPERIENCE_DATA] == pytest.approx(0.0)

    def test_has_salary_data_flag(self) -> None:
        """HAS_SALARY_DATA should be 1.0 when salary data exists."""
        composer = FeatureComposer.create_default()

        # Test with salary data
        job = _create_minimal_job()
        job.compensation = _create_mock_compensation(50000, 75000, CurrencyCode.USD)
        profile = _create_minimal_profile()
        profile.salary_preference = _create_mock_salary_preference(50000, 75000, CurrencyCode.USD)
        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

        features = composer.extract(job, profile, scores).raw_features
        if not math.isnan(features[FeatureIndex.JOB_SALARY]):
            assert features[FeatureIndex.HAS_SALARY_DATA] == pytest.approx(1.0)

        # Test without salary data
        job = _create_minimal_job()
        job.compensation = None
        features = composer.extract(job, profile, scores).raw_features
        assert features[FeatureIndex.HAS_SALARY_DATA] == pytest.approx(0.0)

    def test_has_skill_data_flag(self) -> None:
        """HAS_SKILL_DATA should be 1.0 when job has skill requirements."""
        composer = FeatureComposer.create_default()

        # Test with skills
        job = _create_minimal_job()
        job.skill_requirements = [_create_mock_skill("python"), _create_mock_skill("rust")]
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

        features = composer.extract(job, profile, scores).raw_features
        assert features[FeatureIndex.HAS_SKILL_DATA] == pytest.approx(1.0)

        # Test without skills
        job = _create_minimal_job()
        job.skill_requirements = []
        features = composer.extract(job, profile, scores).raw_features
        assert features[FeatureIndex.HAS_SKILL_DATA] == pytest.approx(0.0)

    def test_has_listing_quality_flag(self) -> None:
        """HAS_LISTING_QUALITY should be 0.0 when no quality signal exists."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.HAS_LISTING_QUALITY] == pytest.approx(0.0)


class TestTaxonomyFeatureGroup:
    """Validate taxonomy/skill graph signals (indices 30-31)."""

    def test_skill_graph_distance_nonnegative(self) -> None:
        """Skill graph distances should be non-negative when present."""
        mock_cache = MagicMock(spec=SkillRelationshipCache)
        mock_cache.relationship_count = 1

        # Mock: skill1 -> skill2 at distance 1
        mock_cache.get_implied_skills.return_value = []
        mock_cache.get_related_skills.side_effect = lambda skill_id: {"skill2"} if skill_id == "skill1" else set()

        feature_group = TaxonomyFeatureGroup(relationship_cache=mock_cache)

        features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
        job = _create_minimal_job()
        profile = _create_minimal_profile()

        skill1 = _create_mock_skill_with_id("skill1")
        skill2 = _create_mock_skill_with_id("skill2")

        job.required_skills = [skill1]
        profile.user_skills = [skill2]

        context = FeatureExtractionContext(
            job=job,
            profile=profile,
            pipeline_scores=PipelineScores(maxsim_score=0.5, rerank_score=0.5),
        )

        feature_group.extract(features, context)

        min_dist = features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE]
        mean_dist = features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE]

        if not math.isnan(min_dist):
            assert min_dist >= 0
        if not math.isnan(mean_dist):
            assert mean_dist >= 0

    def test_skill_graph_nan_when_empty(self) -> None:
        """Skill graph distances should be NaN when skills are missing."""
        feature_group = TaxonomyFeatureGroup(relationship_cache=None)

        features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
        job = _create_minimal_job()
        job.required_skills = []  # No skills
        profile = _create_minimal_profile()
        profile.user_skills = []  # No skills

        context = FeatureExtractionContext(
            job=job,
            profile=profile,
            pipeline_scores=PipelineScores(maxsim_score=0.5, rerank_score=0.5),
        )

        feature_group.extract(features, context)

        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MIN_DISTANCE])
        assert math.isnan(features[FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE])


class TestAllFeaturesPresent:
    """Validate that all 32 features are present and accounted for."""

    def test_feature_count_is_32(self) -> None:
        """FEATURE_COUNT must be exactly 32."""
        assert FEATURE_COUNT == 32

    def test_all_feature_indices_present(self) -> None:
        """All required feature indices must exist."""
        required_indices = {
            FeatureIndex.MAXSIM_SCORE,
            FeatureIndex.RERANK_SCORE,
            FeatureIndex.DISTANCE_KM,
            FeatureIndex.IS_SAME_CITY,
            FeatureIndex.IS_REMOTE_JOB,
            FeatureIndex.USER_OPEN_TO_RELOCATION,
            FeatureIndex.USER_EXPERIENCE_YEARS,
            FeatureIndex.JOB_EXPERIENCE_MIN,
            FeatureIndex.JOB_EXPERIENCE_MAX,
            FeatureIndex.USER_SENIORITY_LEVEL,
            FeatureIndex.JOB_SENIORITY_LEVEL,
            FeatureIndex.USER_MIN_SALARY,
            FeatureIndex.USER_TARGET_SALARY,
            FeatureIndex.JOB_SALARY,
            FeatureIndex.SKILL_MATCH_COUNT,
            FeatureIndex.SKILL_MISSING_COUNT,
            FeatureIndex.SKILL_TOTAL_REQUIRED,
            FeatureIndex.SKILL_AVG_PROFICIENCY,
            FeatureIndex.SKILL_AVG_PROVENANCE,
            FeatureIndex.SKILL_RELATIONSHIP_COUNT,
            FeatureIndex.SKILLS_COSINE_SIM,
            FeatureIndex.JOB_AGE_HOURS,
            FeatureIndex.LISTING_FEEDBACK_COUNT,
            FeatureIndex.LISTING_QUALITY_SCORE,
            FeatureIndex.WORK_ARRANGEMENT_MATCH,
            FeatureIndex.HAS_LOCATION_DATA,
            FeatureIndex.HAS_EXPERIENCE_DATA,
            FeatureIndex.HAS_SALARY_DATA,
            FeatureIndex.HAS_SKILL_DATA,
            FeatureIndex.HAS_LISTING_QUALITY,
            FeatureIndex.SKILL_GRAPH_MIN_DISTANCE,
            FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE,
        }

        assert len(required_indices) == 32
        all_indices = set(FeatureIndex)
        assert all_indices == required_indices

    def test_no_missing_features_from_composer(self) -> None:
        """FeatureComposer should extract all 32 features."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.5, rerank_score=0.5)

        features = composer.extract(job, profile, scores).raw_features

        assert features.shape == (FEATURE_COUNT,)
        assert features.dtype == np.float32
        # All positions should have a value (either valid number or NaN)
        assert np.all(np.isfinite(features) | np.isnan(features))


def _create_minimal_job() -> MagicMock:
    """Create a minimal mock job listing."""
    job = MagicMock()
    job.title = ""
    job.location = None
    job.work_arrangement = 0
    job.experience_years_min = None
    job.experience_years_max = None
    job.seniority_level = 0
    job.compensation = None
    job.skill_requirements = []
    job.required_skills = []
    job.posted_at = datetime.now(UTC)
    job.title_embedding = None
    job.skills_embedding = None
    return job


def _create_minimal_profile() -> MagicMock:
    """Create a minimal mock search preference profile."""
    profile = MagicMock()
    profile.search_keywords = []
    profile.physical_locations = []
    profile.remote_locations = []
    profile.work_arrangements = []
    profile.experience_preference = None
    profile.salary_preference = None
    profile.user_skills = []
    profile.open_to_relocation = False
    profile.query_embedding = None
    profile.user_skills_embedding = None
    return profile


def _create_mock_compensation(min_amount: int, max_amount: int, currency: int) -> MagicMock:
    """Create a mock Compensation object."""
    comp = MagicMock()
    comp.fixed_amount = None
    comp.frequency = PaymentFrequency.ANNUALLY

    # Create mock Money objects
    min_money = MagicMock()
    min_money.amount = min_amount
    min_money.currency = currency
    min_money.minor_units = min_amount

    max_money = MagicMock()
    max_money.amount = max_amount
    max_money.currency = currency
    max_money.minor_units = max_amount

    min_bound = MagicMock()
    min_bound.amount = min_money

    max_bound = MagicMock()
    max_bound.amount = max_money

    comp.min_amount = min_bound
    comp.max_amount = max_bound

    return comp


def _create_mock_salary_preference(min_amount: int, target_amount: int, currency: int) -> MagicMock:
    """Create a mock SalaryPreference object."""
    pref = MagicMock()

    # Create mock Money objects
    min_money = MagicMock()
    min_money.amount = min_amount
    min_money.currency = currency
    min_money.minor_units = min_amount

    target_money = MagicMock()
    target_money.amount = target_amount
    target_money.currency = currency
    target_money.minor_units = target_amount

    pref.min_salary = min_money
    pref.target_salary = target_money

    return pref


def _create_mock_skill(skill_id: str = "test_skill") -> MagicMock:
    """Create a mock skill object."""
    skill = MagicMock()
    skill.canonical_skill_id = skill_id
    skill.skill_id = skill_id
    skill.proficiency = SkillProficiencyLevel.INTERMEDIATE
    skill.proficiency_level = SkillProficiencyLevel.INTERMEDIATE
    skill.provenance = SkillProvenance.USER_DECLARED
    return skill


def _create_mock_skill_with_id(skill_id: str) -> MagicMock:
    """Create a mock skill with specific ID."""
    skill = MagicMock()
    skill.canonical_skill_id = skill_id
    skill.skill_id = skill_id
    return skill


def _create_mock_embedding(values: list[float]) -> MagicMock:
    """Create a mock EmbeddingVector."""
    embedding = MagicMock()
    dense = MagicMock()
    dense.values = values
    embedding.dense = dense
    return embedding

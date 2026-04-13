"""Tests for FeatureComposer and feature groups."""

import dataclasses
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
from job_correlation_evaluation_service.services.scoring.features.groups.job_metadata import (
    _compute_job_age_hours,
)
from job_correlation_evaluation_service.services.scoring.features.groups.semantic import (
    _cosine_similarity,
    _get_embedding_values,
)


class TestPipelineScores:
    """Tests for PipelineScores dataclass."""

    def test_is_frozen_dataclass(self) -> None:
        """PipelineScores should be a frozen dataclass."""
        assert dataclasses.is_dataclass(PipelineScores)
        params = getattr(PipelineScores, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_slots(self) -> None:
        """PipelineScores should use __slots__ for memory efficiency."""
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        assert not hasattr(scores, "__dict__")


class TestFeatureExtractionContext:
    """Tests for FeatureExtractionContext dataclass."""

    def test_is_frozen_dataclass(self) -> None:
        """FeatureExtractionContext should be a frozen dataclass."""
        assert dataclasses.is_dataclass(FeatureExtractionContext)
        params = getattr(FeatureExtractionContext, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestFeatureComposer:
    """Tests for FeatureComposer class."""

    def test_extract_returns_correct_shape(self) -> None:
        """Extract must return array of shape (31,)."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert features.shape == (FEATURE_COUNT,)
        assert features.dtype == np.float32

    def test_extract_pipeline_scores(self) -> None:
        """Pipeline scores should be extracted correctly."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.78, rerank_score=0.92)

        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.MAXSIM_SCORE] == pytest.approx(0.78)
        assert features[FeatureIndex.RERANK_SCORE] == pytest.approx(0.92)

    def test_missing_location_returns_nan(self) -> None:
        """Missing job location should return NaN for distance."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.location = None
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.DISTANCE_KM])
        assert features[FeatureIndex.HAS_LOCATION_DATA] == pytest.approx(0.0)

    def test_remote_job_flag(self) -> None:
        """IS_REMOTE_JOB should be 1.0 for remote jobs."""
        from nohiki.common.v1 import WorkArrangement

        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.work_arrangement = WorkArrangement.REMOTE
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.IS_REMOTE_JOB] == pytest.approx(1.0)

    def test_experience_features_raw_values(self) -> None:
        """Experience features should contain raw values from ExperiencePreference."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.experience_years_min = 3
        job.experience_years_max = 7
        profile = _create_minimal_profile()
        profile.experience_preference = MagicMock()
        profile.experience_preference.experience_years = 5
        profile.experience_preference.seniority_levels = []
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.USER_EXPERIENCE_YEARS] == pytest.approx(5.0)
        assert features[FeatureIndex.JOB_EXPERIENCE_MIN] == pytest.approx(3.0)
        assert features[FeatureIndex.JOB_EXPERIENCE_MAX] == pytest.approx(7.0)
        assert features[FeatureIndex.HAS_EXPERIENCE_DATA] == pytest.approx(1.0)

    def test_missing_experience_returns_nan(self) -> None:
        """Missing experience data should return NaN."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.experience_years_min = None
        job.experience_years_max = None
        profile = _create_minimal_profile()
        profile.experience_preference = None
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.USER_EXPERIENCE_YEARS])
        assert math.isnan(features[FeatureIndex.JOB_EXPERIENCE_MIN])
        assert math.isnan(features[FeatureIndex.JOB_EXPERIENCE_MAX])
        assert features[FeatureIndex.HAS_EXPERIENCE_DATA] == pytest.approx(0.0)

    def test_skill_features_granular(self) -> None:
        """Skill features should be granular counts, not composite score."""
        from nohiki.skill.v1 import (
            JobSkillRequirement,
            SkillProficiencyLevel,
            SkillProvenance,
            UserSkillEntry,
        )

        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.skill_requirements = [
            JobSkillRequirement(
                skill_id="python",
                proficiency_level=SkillProficiencyLevel.ADVANCED,
                is_required=True,
            ),
            JobSkillRequirement(
                skill_id="java",
                proficiency_level=SkillProficiencyLevel.INTERMEDIATE,
                is_required=False,
            ),
        ]
        profile = _create_minimal_profile()
        profile.user_skills = [
            UserSkillEntry(
                skill_id="python",
                proficiency=SkillProficiencyLevel.ADVANCED,
                provenance=SkillProvenance.USER_DECLARED,
                provenance_confidence=0.9,
            ),
        ]
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.SKILL_MATCH_COUNT] == pytest.approx(1.0)
        assert features[FeatureIndex.SKILL_MISSING_COUNT] == pytest.approx(1.0)
        assert features[FeatureIndex.SKILL_TOTAL_REQUIRED] == pytest.approx(2.0)
        assert features[FeatureIndex.HAS_SKILL_DATA] == pytest.approx(1.0)

    def test_job_age_hours_raw(self) -> None:
        """JOB_AGE_HOURS should be raw hours for sub-day precision."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.posted_at = datetime.now(UTC) - timedelta(hours=36)
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.JOB_AGE_HOURS] == pytest.approx(36.0, abs=1)

    def test_missing_posted_at_returns_nan(self) -> None:
        """Missing posted_at should return NaN for job age."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.posted_at = None
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.JOB_AGE_HOURS])

    def test_validity_flags_set_correctly(self) -> None:
        """Validity flags should reflect data presence."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.experience_years_min = 3
        job.experience_years_max = 5
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.HAS_EXPERIENCE_DATA] == pytest.approx(1.0)

    def test_semantic_features_nan_when_missing_embeddings(self) -> None:
        """Semantic features should be NaN when embeddings are missing."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.title_embedding = None
        job.skills_embedding = None
        profile = _create_minimal_profile()
        profile.user_skills_embedding = None
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.SKILLS_COSINE_SIM])


class TestCosineSimilarity:
    """Tests for _cosine_similarity function."""

    def test_identical_vectors(self) -> None:
        """Identical vectors should have similarity 1.0."""
        vec = [1.0, 2.0, 3.0]
        assert _cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        """Orthogonal vectors should have similarity 0.0."""
        vec_a = [1.0, 0.0]
        vec_b = [0.0, 1.0]
        assert _cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        """Opposite vectors should have similarity -1.0."""
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [-1.0, -2.0, -3.0]
        assert _cosine_similarity(vec_a, vec_b) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self) -> None:
        """Zero vector should return 0.0 similarity."""
        vec_a = [0.0, 0.0, 0.0]
        vec_b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)


class TestComputeJobAgeHours:
    """Tests for _compute_job_age_hours function."""

    def test_just_now_returns_near_zero(self) -> None:
        """Job posted just now should return near 0 hours."""
        posted_at = datetime.now(UTC)
        assert _compute_job_age_hours(posted_at) == pytest.approx(0.0, abs=0.1)

    def test_old_job_hours(self) -> None:
        """Job posted 48 hours ago should return 48."""
        posted_at = datetime.now(UTC) - timedelta(hours=48)
        assert _compute_job_age_hours(posted_at) == pytest.approx(48.0, abs=0.1)

    def test_sub_day_precision(self) -> None:
        """Should capture sub-day precision from JSearch timestamps."""
        posted_at = datetime.now(UTC) - timedelta(hours=2, minutes=30)
        result = _compute_job_age_hours(posted_at)
        assert result == pytest.approx(2.5, abs=0.1)

    def test_handles_naive_datetime(self) -> None:
        """Should handle naive datetime by assuming UTC."""
        posted_at = datetime.now() - timedelta(hours=24)
        result = _compute_job_age_hours(posted_at)
        assert result >= 23.0


class TestGetEmbeddingValues:
    """Tests for _get_embedding_values function."""

    def test_none_returns_none(self) -> None:
        """None input should return None."""
        assert _get_embedding_values(None) is None

    def test_empty_values_returns_none(self) -> None:
        """Empty values should return None."""
        mock_emb = MagicMock()
        mock_emb.dense = MagicMock()
        mock_emb.dense.values = []
        assert _get_embedding_values(mock_emb) is None

    def test_extracts_values(self) -> None:
        """Should extract values from embedding object."""
        mock_emb = MagicMock()
        mock_emb.dense = MagicMock()
        mock_emb.dense.values = [0.1, 0.2, 0.3]
        result = _get_embedding_values(mock_emb)
        assert result == [0.1, 0.2, 0.3]


class TestSalaryFeatures:
    """Tests for salary feature extraction."""

    def test_salary_features_with_compensation(self) -> None:
        """Salary features should extract raw values when compensation available and currencies match."""
        from nohiki.common.v1 import CurrencyCode, PaymentFrequency

        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.compensation = MagicMock()
        job.compensation.fixed_amount = MagicMock()
        job.compensation.fixed_amount.amount = MagicMock()
        job.compensation.fixed_amount.amount.minor_units = 10000000  # $100,000 in cents
        job.compensation.fixed_amount.amount.currency = CurrencyCode.USD
        job.compensation.frequency = PaymentFrequency.ANNUALLY
        job.compensation.min_amount = None
        job.compensation.max_amount = None

        profile = _create_minimal_profile()
        profile.salary_preference = MagicMock()
        profile.salary_preference.min_salary = MagicMock()
        profile.salary_preference.min_salary.minor_units = 8000000  # $80,000
        profile.salary_preference.min_salary.currency = CurrencyCode.USD
        profile.salary_preference.target_salary = MagicMock()
        profile.salary_preference.target_salary.minor_units = 12000000  # $120,000
        profile.salary_preference.target_salary.currency = CurrencyCode.USD

        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.USER_MIN_SALARY] == pytest.approx(8000000.0)
        assert features[FeatureIndex.USER_TARGET_SALARY] == pytest.approx(12000000.0)
        assert features[FeatureIndex.JOB_SALARY] == pytest.approx(10000000.0)
        assert features[FeatureIndex.HAS_SALARY_DATA] == pytest.approx(1.0)

    def test_salary_features_no_compensation(self) -> None:
        """Salary features should be NaN when no compensation."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.compensation = None

        profile = _create_minimal_profile()
        profile.salary_preference = None

        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.USER_MIN_SALARY])
        assert math.isnan(features[FeatureIndex.USER_TARGET_SALARY])
        assert math.isnan(features[FeatureIndex.JOB_SALARY])
        assert features[FeatureIndex.HAS_SALARY_DATA] == pytest.approx(0.0)

    def test_salary_range_uses_midpoint(self) -> None:
        """Job salary should use midpoint when range specified."""
        from nohiki.common.v1 import CurrencyCode, PaymentFrequency

        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.compensation = MagicMock()
        job.compensation.fixed_amount = None
        job.compensation.min_amount = MagicMock()
        job.compensation.min_amount.amount = MagicMock()
        job.compensation.min_amount.amount.minor_units = 8000000
        job.compensation.min_amount.amount.currency = CurrencyCode.USD
        job.compensation.max_amount = MagicMock()
        job.compensation.max_amount.amount = MagicMock()
        job.compensation.max_amount.amount.minor_units = 12000000
        job.compensation.max_amount.amount.currency = CurrencyCode.USD
        job.compensation.frequency = PaymentFrequency.ANNUALLY

        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.JOB_SALARY] == pytest.approx(10000000.0)

    def test_salary_features_currency_mismatch_returns_nan(self) -> None:
        """All salary features should be NaN when user and job currencies differ."""
        from nohiki.common.v1 import CurrencyCode, PaymentFrequency

        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.compensation = MagicMock()
        job.compensation.fixed_amount = MagicMock()
        job.compensation.fixed_amount.amount = MagicMock()
        job.compensation.fixed_amount.amount.minor_units = 10000000
        job.compensation.fixed_amount.amount.currency = CurrencyCode.EUR
        job.compensation.frequency = PaymentFrequency.ANNUALLY
        job.compensation.min_amount = None
        job.compensation.max_amount = None

        profile = _create_minimal_profile()
        profile.salary_preference = MagicMock()
        profile.salary_preference.min_salary = MagicMock()
        profile.salary_preference.min_salary.minor_units = 8000000
        profile.salary_preference.min_salary.currency = CurrencyCode.USD  # USD - mismatch!
        profile.salary_preference.target_salary = MagicMock()
        profile.salary_preference.target_salary.minor_units = 12000000
        profile.salary_preference.target_salary.currency = CurrencyCode.USD

        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.USER_MIN_SALARY])
        assert math.isnan(features[FeatureIndex.USER_TARGET_SALARY])
        assert math.isnan(features[FeatureIndex.JOB_SALARY])


class TestSemanticFeatures:
    """Tests for semantic feature extraction."""

    def test_semantic_features_with_embeddings(self) -> None:
        """Semantic features should compute cosine similarity when embeddings present."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.skills_embedding = MagicMock()
        job.skills_embedding.dense = MagicMock()
        job.skills_embedding.dense.values = [0.0, 1.0, 0.0]

        profile = _create_minimal_profile()
        profile.user_skills_embedding = MagicMock()
        profile.user_skills_embedding.dense = MagicMock()
        profile.user_skills_embedding.dense.values = [0.0, 1.0, 0.0]

        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        features = composer.extract(job, profile, scores).raw_features

        # Job skills [0,1,0] vs user skills [0,1,0] → identical → 1.0
        assert features[FeatureIndex.SKILLS_COSINE_SIM] == pytest.approx(1.0)


class TestWorkArrangementFeatures:
    """Tests for work arrangement feature extraction."""

    def test_work_arrangement_match(self) -> None:
        """Work arrangement match should be 1.0 when job matches preference."""
        from nohiki.common.v1 import WorkArrangement

        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.work_arrangement = WorkArrangement.HYBRID

        profile = _create_minimal_profile()
        profile.work_arrangements = [WorkArrangement.HYBRID, WorkArrangement.REMOTE]

        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.WORK_ARRANGEMENT_MATCH] == pytest.approx(1.0)

    def test_work_arrangement_no_match(self) -> None:
        """Work arrangement match should be 0.0 when job doesn't match preference."""
        from nohiki.common.v1 import WorkArrangement

        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.work_arrangement = WorkArrangement.ON_SITE

        profile = _create_minimal_profile()
        profile.work_arrangements = [WorkArrangement.REMOTE]

        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.WORK_ARRANGEMENT_MATCH] == pytest.approx(0.0)

    def test_work_arrangement_nan_when_unspecified(self) -> None:
        """Work arrangement match should be NaN when job arrangement unspecified."""
        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.work_arrangement = 0  # UNSPECIFIED

        profile = _create_minimal_profile()
        profile.work_arrangements = [1, 2]  # Some preferences

        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        features = composer.extract(job, profile, scores).raw_features

        assert math.isnan(features[FeatureIndex.WORK_ARRANGEMENT_MATCH])


class TestSeniorityFeatures:
    """Tests for seniority feature extraction."""

    def test_seniority_features_with_data(self) -> None:
        """Seniority features should extract ordinal values from ExperiencePreference."""
        from nohiki.common.v1 import SeniorityLevel

        composer = FeatureComposer.create_default()
        job = _create_minimal_job()
        job.seniority_level = SeniorityLevel.SENIOR

        profile = _create_minimal_profile()
        profile.experience_preference = MagicMock()
        profile.experience_preference.experience_years = 5
        profile.experience_preference.seniority_levels = [SeniorityLevel.MID, SeniorityLevel.SENIOR]

        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)
        features = composer.extract(job, profile, scores).raw_features

        assert features[FeatureIndex.JOB_SENIORITY_LEVEL] == pytest.approx(4.0)
        assert features[FeatureIndex.USER_SENIORITY_LEVEL] == pytest.approx(4.0)


class TestListingQualityFeatures:
    """Tests for listing quality feature extraction."""

    def test_listing_quality_with_predictor(self) -> None:
        """Listing quality should use predictor when available."""
        from job_correlation_evaluation_service.services.scoring.listing_quality import (
            ListingFeedbackAggregate,
            ListingQualityPredictor,
        )

        mock_predictor = MagicMock(spec=ListingQualityPredictor)
        mock_predictor.predict.return_value = 0.85

        composer = FeatureComposer.create_default(listing_quality_predictor=mock_predictor)
        job = _create_minimal_job()
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        mock_feedback = MagicMock(spec=ListingFeedbackAggregate)
        mock_feedback.total_feedback = 10

        features = composer.extract(job, profile, scores, feedback_aggregate=mock_feedback).raw_features

        assert features[FeatureIndex.LISTING_QUALITY_SCORE] == pytest.approx(0.85)
        assert features[FeatureIndex.LISTING_FEEDBACK_COUNT] == pytest.approx(10.0)
        assert features[FeatureIndex.HAS_LISTING_QUALITY] == pytest.approx(1.0)

    def test_listing_quality_no_predictor(self) -> None:
        """Listing quality should be NaN when no predictor."""
        composer = FeatureComposer.create_default(listing_quality_predictor=None)
        job = _create_minimal_job()
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        features = composer.extract(job, profile, scores, feedback_aggregate=None).raw_features

        assert math.isnan(features[FeatureIndex.LISTING_QUALITY_SCORE])
        assert features[FeatureIndex.LISTING_FEEDBACK_COUNT] == pytest.approx(0.0)
        assert features[FeatureIndex.HAS_LISTING_QUALITY] == pytest.approx(0.0)


class TestFeatureComposerExceptionHandling:
    """Tests for exception handling in feature extraction."""

    def test_extract_records_failure_metrics(self) -> None:
        """Test that exceptions record failure metrics before re-raising."""
        from job_correlation_evaluation_service.services.scoring.features.base import (
            FeatureGroup,
            PipelineScores,
        )

        class FailingFeatureGroup(FeatureGroup):
            """Feature group that always fails."""

            def extract(self, features: np.ndarray, context: FeatureExtractionContext) -> None:
                msg = "Simulated extraction failure"
                raise RuntimeError(msg)

        composer = FeatureComposer([FailingFeatureGroup()])
        job = _create_minimal_job()
        profile = _create_minimal_profile()
        scores = PipelineScores(maxsim_score=0.8, rerank_score=0.9)

        with pytest.raises(RuntimeError, match="Simulated extraction failure"):
            composer.extract(job, profile, scores)


class TestLocationFeaturesWithData:
    """Tests for location features when job and profile locations exist."""

    def test_location_features_with_both_locations(self) -> None:
        """Test location features extracted when job and profile locations exist."""
        from job_correlation_evaluation_service.services.scoring.features.groups.location import (
            LocationFeatureGroup,
        )
        from job_correlation_evaluation_service.services.scoring.features.location_scorer import (
            LocationMatchResult,
            LocationScenario,
        )
        from nohiki.common.v1 import WorkArrangement

        mock_scorer = MagicMock()
        mock_scorer.score.return_value = LocationMatchResult(
            score=0.85,
            is_scoreable=True,
            scenario=LocationScenario.LOCAL_COMMUTE,
            distance_km=15.5,
            is_same_city=False,
            fallback_reason=None,
        )

        feature_group = LocationFeatureGroup(location_scorer=mock_scorer)

        features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)
        job = _create_minimal_job()
        job.location = MagicMock()
        job.work_arrangement = WorkArrangement.REMOTE

        profile = _create_minimal_profile()
        profile.physical_locations = [MagicMock()]
        profile.remote_locations = []
        profile.open_to_relocation = True
        profile.work_arrangements = [WorkArrangement.REMOTE, WorkArrangement.HYBRID]

        context = FeatureExtractionContext(
            job=job,
            profile=profile,
            pipeline_scores=PipelineScores(maxsim_score=0.8, rerank_score=0.9),
            feedback_aggregate=None,
        )

        feature_group.extract(features, context)

        assert features[FeatureIndex.DISTANCE_KM] == pytest.approx(15.5)
        assert features[FeatureIndex.IS_SAME_CITY] == pytest.approx(0.0)
        assert features[FeatureIndex.IS_REMOTE_JOB] == pytest.approx(1.0)
        assert features[FeatureIndex.USER_OPEN_TO_RELOCATION] == pytest.approx(1.0)


def _create_minimal_job() -> MagicMock:
    """Create a minimal mock job listing."""
    job = MagicMock()
    job.location = None
    job.work_arrangement = 0
    job.experience_years_min = None
    job.experience_years_max = None
    job.seniority_level = 0
    job.compensation = None
    job.skill_requirements = []
    job.posted_at = datetime.now(UTC)
    job.title_embedding = None
    job.skills_embedding = None
    return job


def _create_minimal_profile() -> MagicMock:
    """Create a minimal mock search preference profile."""
    profile = MagicMock()
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

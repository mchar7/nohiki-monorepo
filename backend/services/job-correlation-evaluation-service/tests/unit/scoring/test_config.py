"""Unit tests for scoring configuration module.

Tests the centralized Pydantic Settings configuration for scoring parameters.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from job_correlation_evaluation_service.services.scoring.config import (
    CountNormalizationConfig,
    ExperienceScoringConfig,
    FreshnessScoringConfig,
    ListingQualityScoringConfig,
    LocationScoringConfig,
    ScoringServiceSettings,
    SkillScoringConfig,
    get_scoring_config,
    get_scoring_service_settings,
    reset_scoring_service_settings,
)


class TestLocationScoringConfig:
    """Tests for LocationScoringConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = LocationScoringConfig()

        assert config.decay_beta == pytest.approx(0.03)
        assert config.hybrid_distance_multiplier == pytest.approx(1.2)
        assert config.same_city_threshold_km == pytest.approx(30.0)
        assert config.relocation_decay_multiplier == pytest.approx(0.3)
        assert config.city_match_score == pytest.approx(0.95)
        assert config.state_match_score == pytest.approx(0.75)
        assert config.country_match_score == pytest.approx(0.55)

    def test_commute_breakpoints_property(self) -> None:
        """Test commute_breakpoints property returns correct values."""
        config = LocationScoringConfig()
        breakpoints = config.commute_breakpoints

        assert len(breakpoints) == 6
        assert breakpoints[0] == (0.0, 1.0)
        assert breakpoints[-1] == (200.0, 0.0)

    def test_values_in_valid_range(self) -> None:
        """Test all values are in valid ranges."""
        config = LocationScoringConfig()

        assert 0.0 < config.decay_beta < 1.0
        assert config.hybrid_distance_multiplier > 1.0
        assert config.same_city_threshold_km > 0.0
        assert 0.0 < config.relocation_decay_multiplier < 1.0
        assert 0.0 < config.city_match_score <= 1.0
        assert 0.0 < config.state_match_score <= 1.0
        assert 0.0 < config.country_match_score <= 1.0


class TestExperienceScoringConfig:
    """Tests for ExperienceScoringConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = ExperienceScoringConfig()

        assert config.overqualified_max_penalty_years == 5
        assert config.overqualified_min_score == pytest.approx(0.5)
        assert config.underqualified_max_penalty_years == 3
        assert config.underqualified_min_score == pytest.approx(0.3)
        assert config.seniority_one_level_score == pytest.approx(0.8)
        assert config.seniority_two_level_score == pytest.approx(0.5)
        assert config.seniority_three_plus_score == pytest.approx(0.2)
        assert config.max_experience_years == 30

    def test_seniority_scores_decreasing(self) -> None:
        """Test seniority scores decrease with distance."""
        config = ExperienceScoringConfig()

        assert config.seniority_one_level_score > config.seniority_two_level_score
        assert config.seniority_two_level_score > config.seniority_three_plus_score

    def test_min_scores_in_valid_range(self) -> None:
        """Test minimum scores are in valid range."""
        config = ExperienceScoringConfig()

        assert 0.0 < config.overqualified_min_score < 1.0
        assert 0.0 < config.underqualified_min_score < 1.0


class TestFreshnessScoringConfig:
    """Tests for FreshnessScoringConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = FreshnessScoringConfig()

        assert config.max_age_days == 30

    def test_max_age_reasonable(self) -> None:
        """Test max age is reasonable (14-60 days)."""
        config = FreshnessScoringConfig()

        assert 14 <= config.max_age_days <= 60


class TestSkillScoringConfig:
    """Tests for SkillScoringConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SkillScoringConfig()

        assert config.proficiency_weight == pytest.approx(0.4)
        assert config.provenance_weight == pytest.approx(0.3)
        assert config.coverage_weight == pytest.approx(0.3)
        assert config.required_skill_multiplier == pytest.approx(1.5)
        assert config.gap_penalty_per_level == pytest.approx(0.2)
        assert config.min_gap_multiplier == pytest.approx(0.3)
        assert config.relationship_bonus_weight == pytest.approx(0.1)

    def test_weights_sum_to_one(self) -> None:
        """Test main scoring weights sum to approximately 1.0."""
        config = SkillScoringConfig()

        total = config.proficiency_weight + config.provenance_weight + config.coverage_weight
        assert total == pytest.approx(1.0)

    def test_all_weights_positive(self) -> None:
        """Test all weights are positive."""
        config = SkillScoringConfig()

        assert config.proficiency_weight > 0
        assert config.provenance_weight > 0
        assert config.coverage_weight > 0
        assert config.required_skill_multiplier > 0
        assert config.gap_penalty_per_level > 0
        assert config.min_gap_multiplier > 0
        assert config.relationship_bonus_weight > 0


class TestListingQualityScoringConfig:
    """Tests for ListingQualityScoringConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = ListingQualityScoringConfig()

        assert config.too_high_penalty == pytest.approx(0.4)
        assert config.too_low_bonus == pytest.approx(0.2)
        assert config.neutral_quality == pytest.approx(0.5)
        assert config.min_feedback_for_signal == 5

    def test_neutral_quality_is_midpoint(self) -> None:
        """Test neutral quality is at midpoint of [0, 1]."""
        config = ListingQualityScoringConfig()

        assert config.neutral_quality == pytest.approx(0.5)


class TestCountNormalizationConfig:
    """Tests for CountNormalizationConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = CountNormalizationConfig()

        assert config.max_feedback_count == 100
        assert config.max_skill_count == 100
        assert config.max_experience_years == 30

    def test_max_counts_positive(self) -> None:
        """Test max counts are positive."""
        config = CountNormalizationConfig()

        assert config.max_feedback_count > 0
        assert config.max_skill_count > 0
        assert config.max_experience_years > 0


class TestScoringServiceSettings:
    """Tests for ScoringServiceSettings (main settings class)."""

    def test_default_values(self) -> None:
        """Test default settings values."""
        settings = ScoringServiceSettings()

        assert settings.embedding_model == "mxbai-edge-colbert-v0-17m"
        assert settings.embedding_dimension == 2048
        assert settings.use_cross_encoder_single is False
        assert settings.use_cross_encoder_batch is True
        assert settings.cross_encoder_top_k == 50

    def test_nested_configs_initialized(self) -> None:
        """Test nested config objects are properly initialized."""
        settings = ScoringServiceSettings()

        assert isinstance(settings.location, LocationScoringConfig)
        assert isinstance(settings.experience, ExperienceScoringConfig)
        assert isinstance(settings.freshness, FreshnessScoringConfig)
        assert isinstance(settings.skill, SkillScoringConfig)
        assert isinstance(settings.listing_quality, ListingQualityScoringConfig)
        assert isinstance(settings.count_normalization, CountNormalizationConfig)

    def test_cross_encoder_settings(self) -> None:
        """Test cross-encoder settings."""
        settings = ScoringServiceSettings()

        assert settings.use_cross_encoder_single is False
        assert settings.use_cross_encoder_batch is True
        assert settings.cross_encoder_top_k == 50

    def test_timeout_settings(self) -> None:
        """Test timeout settings are positive."""
        settings = ScoringServiceSettings()

        assert settings.embedding_retrieval_timeout_seconds > 0
        assert settings.cross_encoder_timeout_seconds > 0
        assert settings.l2r_inference_timeout_seconds > 0


class TestSingletonPattern:
    """Tests for singleton pattern implementation."""

    def teardown_method(self) -> None:
        """Reset singleton after each test."""
        reset_scoring_service_settings()

    def test_get_scoring_service_settings_returns_same_instance(self) -> None:
        """Test singleton returns same instance."""
        instance1 = get_scoring_service_settings()
        instance2 = get_scoring_service_settings()

        assert instance1 is instance2

    def test_reset_scoring_service_settings_clears_singleton(self) -> None:
        """Test reset clears the singleton."""
        instance1 = get_scoring_service_settings()
        reset_scoring_service_settings()
        instance2 = get_scoring_service_settings()

        assert instance1 is not instance2

    def test_get_scoring_config_alias_returns_same_instance(self) -> None:
        """Test get_scoring_config is an alias for get_scoring_service_settings."""
        instance1 = get_scoring_service_settings()
        instance2 = get_scoring_config()

        assert instance1 is instance2


class TestEnvironmentVariableOverrides:
    """Tests for environment variable configuration overrides."""

    def teardown_method(self) -> None:
        """Reset singleton after each test."""
        reset_scoring_service_settings()

    def test_location_config_env_override(self) -> None:
        """Test location config can be overridden via environment variables."""
        with patch.dict(os.environ, {"SCORING_LOCATION__DECAY_BETA": "0.05"}):
            reset_scoring_service_settings()
            config = LocationScoringConfig()
            assert config.decay_beta == pytest.approx(0.05)

    def test_experience_config_env_override(self) -> None:
        """Test experience config can be overridden via environment variables."""
        with patch.dict(os.environ, {"SCORING_EXPERIENCE__MAX_EXPERIENCE_YEARS": "40"}):
            reset_scoring_service_settings()
            config = ExperienceScoringConfig()
            assert config.max_experience_years == 40

    def test_freshness_config_env_override(self) -> None:
        """Test freshness config can be overridden via environment variables."""
        with patch.dict(os.environ, {"SCORING_FRESHNESS__MAX_AGE_DAYS": "45"}):
            reset_scoring_service_settings()
            config = FreshnessScoringConfig()
            assert config.max_age_days == 45

    def test_skill_config_env_override(self) -> None:
        """Test skill config can be overridden via environment variables."""
        with patch.dict(os.environ, {"SCORING_SKILL__PROFICIENCY_WEIGHT": "0.5"}):
            reset_scoring_service_settings()
            config = SkillScoringConfig()
            assert config.proficiency_weight == pytest.approx(0.5)

    def test_listing_quality_config_env_override(self) -> None:
        """Test listing quality config can be overridden via environment variables."""
        with patch.dict(os.environ, {"SCORING_LISTING_QUALITY__MIN_FEEDBACK_FOR_SIGNAL": "10"}):
            reset_scoring_service_settings()
            config = ListingQualityScoringConfig()
            assert config.min_feedback_for_signal == 10

    def test_count_normalization_config_env_override(self) -> None:
        """Test count normalization config can be overridden via environment variables."""
        with patch.dict(os.environ, {"SCORING_COUNT__MAX_FEEDBACK_COUNT": "200"}):
            reset_scoring_service_settings()
            config = CountNormalizationConfig()
            assert config.max_feedback_count == 200

"""Scoring service configuration.

Centralized configuration for all scoring parameters using Pydantic Settings.
This replaces scattered magic constants throughout the codebase and enables
environment variable overrides for flexibility.

Environment Variable Patterns:
    SCORING_L2R_MODEL_PATH=...           # Service-level settings
    SCORING_LOCATION__DECAY_BETA=0.03    # Nested location config
    SCORING_EXPERIENCE__OVERQUALIFIED_MAX_PENALTY_YEARS=5
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, PositiveFloat, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

# Feature Scoring Configuration Classes


class LocationScoringConfig(BaseSettings):
    """Configuration for location scoring.

    Controls distance decay, commute scoring breakpoints, and administrative
    unit match scores.
    """

    model_config = SettingsConfigDict(
        env_prefix="SCORING_LOCATION__",
        extra="ignore",
    )

    decay_beta: float = Field(
        default=0.03,
        description="Exponential decay rate for distance scoring",
    )
    hybrid_distance_multiplier: float = Field(
        default=1.2,
        description="Effective distance divisor for hybrid work arrangements",
    )
    same_city_threshold_km: float = Field(
        default=30.0,
        description="Maximum distance to consider as same-city match",
    )
    relocation_decay_multiplier: float = Field(
        default=0.3,
        description="Decay rate multiplier for relocation scenarios",
    )
    city_match_score: float = Field(
        default=0.95,
        description="Score for city-level administrative match",
    )
    state_match_score: float = Field(
        default=0.75,
        description="Score for state-level administrative match",
    )
    country_match_score: float = Field(
        default=0.55,
        description="Score for country-level administrative match",
    )

    @property
    def commute_breakpoints(self) -> tuple[tuple[float, float], ...]:
        """Piecewise linear breakpoints for commute scoring (distance_km, score)."""
        return (
            (0.0, 1.0),
            (15.0, 0.9),
            (30.0, 0.7),
            (60.0, 0.4),
            (100.0, 0.1),
            (200.0, 0.0),
        )


class ExperienceScoringConfig(BaseSettings):
    """Configuration for experience and seniority scoring.

    Controls penalties for over/under-qualification and seniority level
    distance scoring.
    """

    model_config = SettingsConfigDict(
        env_prefix="SCORING_EXPERIENCE__",
        extra="ignore",
    )

    overqualified_max_penalty_years: int = Field(
        default=5,
        description="Years overage at which penalty reaches minimum score",
    )
    overqualified_min_score: float = Field(
        default=0.5,
        description="Minimum score for maximally overqualified candidates",
    )
    underqualified_max_penalty_years: int = Field(
        default=3,
        description="Years underage at which penalty reaches minimum score",
    )
    underqualified_min_score: float = Field(
        default=0.3,
        description="Minimum score for maximally underqualified candidates",
    )
    seniority_one_level_score: float = Field(
        default=0.8,
        description="Score when job seniority is one level from preference",
    )
    seniority_two_level_score: float = Field(
        default=0.5,
        description="Score when job seniority is two levels from preference",
    )
    seniority_three_plus_score: float = Field(
        default=0.2,
        description="Score when job seniority is three+ levels from preference",
    )
    max_experience_years: int = Field(
        default=30,
        description="Maximum experience years when job has no upper bound",
    )


class FreshnessScoringConfig(BaseSettings):
    """Configuration for job freshness scoring."""

    model_config = SettingsConfigDict(
        env_prefix="SCORING_FRESHNESS__",
        extra="ignore",
    )

    max_age_days: int = Field(
        default=30,
        description="Maximum age in days for non-zero freshness score",
    )


class SkillScoringConfig(BaseSettings):
    """Configuration for skill match quality scoring.

    Controls proficiency weights, provenance weights, and component weights
    for the composite skill match score.
    """

    model_config = SettingsConfigDict(
        env_prefix="SCORING_SKILL__",
        extra="ignore",
    )

    proficiency_weight: float = Field(
        default=0.4,
        description="Weight for proficiency score in final calculation",
    )
    provenance_weight: float = Field(
        default=0.3,
        description="Weight for provenance score in final calculation",
    )
    coverage_weight: float = Field(
        default=0.3,
        description="Weight for coverage score in final calculation",
    )
    required_skill_multiplier: float = Field(
        default=1.5,
        description="Multiplier for required skills vs nice-to-have",
    )
    gap_penalty_per_level: float = Field(
        default=0.2,
        description="Penalty per proficiency level gap",
    )
    min_gap_multiplier: float = Field(
        default=0.3,
        description="Minimum multiplier after gap penalty",
    )
    relationship_bonus_weight: float = Field(
        default=0.1,
        description="Weight for relationship expansion bonus",
    )


class ListingQualityScoringConfig(BaseSettings):
    """Configuration for listing quality scoring from feedback."""

    model_config = SettingsConfigDict(
        env_prefix="SCORING_LISTING_QUALITY__",
        extra="ignore",
    )

    too_high_penalty: float = Field(
        default=0.4,
        description="Penalty weight for TOO_HIGH feedback ratio",
    )
    too_low_bonus: float = Field(
        default=0.2,
        description="Bonus weight for TOO_LOW feedback ratio",
    )
    neutral_quality: float = Field(
        default=0.5,
        description="Neutral quality score when no signal available",
    )
    min_feedback_for_signal: int = Field(
        default=5,
        description="Minimum feedback count to produce quality signal",
    )


class CountNormalizationConfig(BaseSettings):
    """Configuration for count feature normalization."""

    model_config = SettingsConfigDict(
        env_prefix="SCORING_COUNT__",
        extra="ignore",
    )

    max_feedback_count: int = Field(
        default=100,
        description="Count at which feedback normalizes to 1.0",
    )
    max_skill_count: int = Field(
        default=100,
        description="Count at which skill requirements normalize to 1.0",
    )
    max_experience_years: int = Field(
        default=30,
        description="Maximum experience years for normalization",
    )


# Scoring Service Settings (Model/Infrastructure)


class ScoringServiceSettings(BaseSettings):
    """Scoring service configuration.

    Combines L2R model settings, embedding settings, operational parameters,
    and feature scoring configuration.
    """

    model_config = SettingsConfigDict(
        env_prefix="SCORING_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        env_nested_delimiter="__",
    )

    # Embedding settings
    embedding_model: str = Field(
        default="mxbai-edge-colbert-v0-17m",
        description="Embedding model identifier for ColBERT encoding",
    )
    embedding_dimension: PositiveInt = Field(
        default=2048,
        description="MUVERA FDE embedding dimension",
    )

    # Cross-encoder settings
    use_cross_encoder_single: bool = Field(
        default=False,
        description="Use cross-encoder (LLM rerank) for single scoring",
    )
    use_cross_encoder_batch: bool = Field(
        default=True,
        description="Use cross-encoder (LLM rerank) for batch scoring",
    )
    cross_encoder_top_k: PositiveInt = Field(
        default=50,
        description="Number of top candidates to send to cross-encoder",
    )

    # Timeouts
    embedding_retrieval_timeout_seconds: PositiveFloat = Field(
        default=2.0,
        description="Timeout for embedding retrieval from cache/storage",
    )
    cross_encoder_timeout_seconds: PositiveFloat = Field(
        default=5.0,
        description="Timeout for cross-encoder (LLM rerank) requests",
    )
    l2r_inference_timeout_seconds: PositiveFloat = Field(
        default=1.0,
        description="Timeout for L2R model inference",
    )

    # Nested feature scoring configs
    location: LocationScoringConfig = Field(default_factory=LocationScoringConfig)
    experience: ExperienceScoringConfig = Field(default_factory=ExperienceScoringConfig)
    freshness: FreshnessScoringConfig = Field(default_factory=FreshnessScoringConfig)
    skill: SkillScoringConfig = Field(default_factory=SkillScoringConfig)
    listing_quality: ListingQualityScoringConfig = Field(default_factory=ListingQualityScoringConfig)
    count_normalization: CountNormalizationConfig = Field(default_factory=CountNormalizationConfig)


# Singleton Access


class _ScoringServiceSettingsHolder:
    """Holder class for singleton pattern to avoid global statement warnings."""

    instance: ScoringServiceSettings | None = None


def get_scoring_service_settings() -> ScoringServiceSettings:
    """Get cached scoring service settings instance."""
    if _ScoringServiceSettingsHolder.instance is None:
        _ScoringServiceSettingsHolder.instance = ScoringServiceSettings()
    return _ScoringServiceSettingsHolder.instance


def reset_scoring_service_settings() -> None:
    """Reset the scoring service settings singleton (for testing)."""
    _ScoringServiceSettingsHolder.instance = None


@lru_cache
def get_scoring_config() -> ScoringServiceSettings:
    """Alias for get_scoring_service_settings for compatibility."""
    return get_scoring_service_settings()

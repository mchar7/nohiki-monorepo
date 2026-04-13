"""Pydantic schemas for scoring system outputs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .constants import FEATURE_COUNT, FeatureIndex


class ExtractedSkill(BaseModel):
    """Single extracted skill from job description or profile."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Normalized skill name")
    category: str = Field(..., description="Skill category (e.g., programming_language, framework)")
    proficiency: Literal["required", "preferred", "nice_to_have"] = Field(
        default="required",
        description="How important this skill is for the role",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="LLM extraction confidence")


class SkillExtractionResult(BaseModel):
    """Result of LLM skill extraction from text."""

    model_config = ConfigDict(frozen=True)

    skills: list[ExtractedSkill] = Field(default_factory=list)
    extraction_confidence: Literal["high", "medium", "low"] = Field(
        default="medium",
        description="Overall extraction quality assessment",
    )
    raw_skill_count: int = Field(default=0, description="Count before deduplication/normalization")


class JobMetadataExtraction(BaseModel):
    """Extracted metadata from job description via LLM."""

    model_config = ConfigDict(frozen=True)

    seniority_level: str | None = Field(default=None, description="e.g., junior, mid, senior, lead")
    experience_years_min: int | None = Field(default=None, ge=0, le=50)
    experience_years_max: int | None = Field(default=None, ge=0, le=50)
    work_location_type: Literal["remote", "hybrid", "onsite", "unknown"] = Field(
        default="unknown",
        description="Work arrangement type",
    )
    salary_min: int | None = Field(default=None, ge=0, description="Minimum salary in local currency")
    salary_max: int | None = Field(default=None, ge=0, description="Maximum salary in local currency")
    salary_currency: str | None = Field(default=None, max_length=3, description="ISO 4217 currency code")


class FeatureVector(BaseModel):
    """L2R feature vector for scoring."""

    model_config = ConfigDict(frozen=True)

    values: list[float] = Field(
        ...,
        min_length=FEATURE_COUNT,
        max_length=FEATURE_COUNT,
        description=f"Feature vector with exactly {FEATURE_COUNT} elements",
    )

    def get_feature(self, index: FeatureIndex) -> float:
        """Get feature value by index enum."""
        return self.values[index.value]


class ScoringResult(BaseModel):
    """Result of the 4-stage scoring pipeline."""

    model_config = ConfigDict(frozen=True)

    correlation_id: str = Field(..., description="Unique correlation identifier")
    listing_id: str = Field(..., description="Job listing ID")
    pref_id: str = Field(..., description="Search preference ID")
    final_score: float = Field(..., ge=0.0, le=100.0, description="Final L2R score (0-100)")
    feature_vector: FeatureVector = Field(..., description="L2R input features")

    # Stage scores (for debugging/explanation)
    maxsim_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Stage 2: ColBERT MaxSim")
    rerank_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Stage 3: LLM reranker")

    # Metadata
    stages_completed: list[str] = Field(default_factory=list, description="Pipeline stages that completed")
    collection_version: str = Field(..., description="Collection version from manifest (e.g., 'v1')")


class SkillMatchResult(BaseModel):
    """Result of skill matching between job and profile."""

    model_config = ConfigDict(frozen=True)

    matched_skills: list[str] = Field(default_factory=list, description="Skills present in both")
    missing_skills: list[str] = Field(default_factory=list, description="Required skills not in profile")
    extra_skills: list[str] = Field(default_factory=list, description="Profile skills not required")
    match_ratio: float = Field(..., ge=0.0, le=1.0, description="matched / total required")


class RerankCandidate(BaseModel):
    """Candidate for LLM reranking."""

    model_config = ConfigDict(frozen=True)

    listing_id: str = Field(..., description="Job listing ID")
    rank: int = Field(..., ge=0, description="Rank from previous stage")
    text: str = Field(..., description="Document text for reranking")
    metadata: dict[str, str] = Field(default_factory=dict, description="Additional metadata")


class RerankResult(BaseModel):
    """Result of LLM reranking."""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(..., description="Original request ID for correlation")
    reranked_ids: list[str] = Field(..., description="Listing IDs in reranked order")
    scores: list[float] = Field(..., description="Reranker scores (same order as reranked_ids)")

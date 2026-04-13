"""Configuration for 4-Stage Scoring Pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from job_correlation_evaluation_service.core.config import get_settings

if TYPE_CHECKING:
    from job_correlation_evaluation_service.core.config import Settings


class MaxSimMode(StrEnum):
    """MaxSim computation mode for Stage 2."""

    NATIVE = "native"  # Qdrant native multi-vector MaxSim


class PipelineStageSettings(BaseSettings):
    """Settings for deterministic pipeline stages."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    # Stage 1: MUVERA ANN
    stage1_candidate_limit: int = Field(
        default=1000,
        validation_alias="PIPELINE_STAGE1_CANDIDATE_LIMIT",
        description="Maximum candidates from MUVERA ANN retrieval",
    )

    # Stage 2: MaxSim Rerank
    stage2_candidate_limit: int = Field(
        default=150,
        validation_alias="PIPELINE_STAGE2_CANDIDATE_LIMIT",
        description="Maximum candidates for MaxSim precision reranking",
    )
    stage2_mode: MaxSimMode = Field(
        default=MaxSimMode.NATIVE,
        validation_alias="PIPELINE_STAGE2_MODE",
        description="MaxSim computation mode: 'native' (Qdrant multi-vector)",
    )
    stage2_prefetch_limit: int = Field(
        default=200,
        validation_alias="PIPELINE_STAGE2_PREFETCH_LIMIT",
        description="Prefetch candidates for native MaxSim mode",
    )

    # Stage 3: LLM Rerank
    stage3_enabled: bool = Field(
        default=False,
        validation_alias="PIPELINE_STAGE3_ENABLED",
        description="Enable LLM reranking stage",
    )
    stage3_candidate_limit: int = Field(
        default=50,
        validation_alias="PIPELINE_STAGE3_CANDIDATE_LIMIT",
        description="Maximum candidates for LLM reranking",
    )
    reranker_endpoint_url: str = Field(
        default="",
        validation_alias="PIPELINE_RERANKER_ENDPOINT_URL",
        description="External reranker endpoint URL (model-agnostic)",
    )
    rerank_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="PIPELINE_RERANK_TIMEOUT_SECONDS",
        description="Reranker request timeout in seconds",
    )
    rerank_batch_size: int = Field(
        default=16,
        validation_alias="PIPELINE_RERANK_BATCH_SIZE",
        description="Batch size for reranking requests",
    )

    # Circuit Breaker
    circuit_breaker_failure_threshold: int = Field(
        default=5,
        validation_alias="PIPELINE_CIRCUIT_FAILURE_THRESHOLD",
        description="Circuit breaker failure threshold",
    )
    circuit_breaker_recovery_seconds: int = Field(
        default=30,
        validation_alias="PIPELINE_CIRCUIT_RECOVERY_SECONDS",
        description="Circuit breaker recovery timeout in seconds",
    )

    # Scoring blend weights for combining retrieval signals
    weight_maxsim: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        validation_alias="PIPELINE_WEIGHT_MAXSIM",
        description="Blend weight for ColBERT MaxSim score",
    )
    weight_title: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        validation_alias="PIPELINE_WEIGHT_TITLE",
        description="Blend weight for title semantic similarity score",
    )
    sparse_boost_weight: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        validation_alias="PIPELINE_SPARSE_BOOST_WEIGHT",
        description="Sparse lexical boost weight in hybrid scoring",
    )


@dataclass(frozen=True, slots=True)
class PipelineSettings:
    """Combined deterministic pipeline settings."""

    stage1_candidate_limit: int
    stage2_candidate_limit: int
    stage2_mode: MaxSimMode
    stage2_prefetch_limit: int
    stage3_enabled: bool
    stage3_candidate_limit: int
    reranker_endpoint_url: str
    rerank_timeout_seconds: float
    rerank_batch_size: int
    circuit_breaker_failure_threshold: int
    circuit_breaker_recovery_seconds: int
    weight_maxsim: float
    weight_title: float
    sparse_boost_weight: float


def build_pipeline_settings(main_settings: Settings) -> PipelineSettings:
    """Build deterministic pipeline settings."""
    del main_settings
    stage_settings = PipelineStageSettings()
    return PipelineSettings(
        stage1_candidate_limit=stage_settings.stage1_candidate_limit,
        stage2_candidate_limit=stage_settings.stage2_candidate_limit,
        stage2_mode=stage_settings.stage2_mode,
        stage2_prefetch_limit=stage_settings.stage2_prefetch_limit,
        stage3_enabled=stage_settings.stage3_enabled,
        stage3_candidate_limit=stage_settings.stage3_candidate_limit,
        reranker_endpoint_url=stage_settings.reranker_endpoint_url,
        rerank_timeout_seconds=stage_settings.rerank_timeout_seconds,
        rerank_batch_size=stage_settings.rerank_batch_size,
        circuit_breaker_failure_threshold=stage_settings.circuit_breaker_failure_threshold,
        circuit_breaker_recovery_seconds=stage_settings.circuit_breaker_recovery_seconds,
        weight_maxsim=stage_settings.weight_maxsim,
        weight_title=stage_settings.weight_title,
        sparse_boost_weight=stage_settings.sparse_boost_weight,
    )


class PipelineConfigManager:
    """Manager for scoring pipeline configuration singleton."""

    _cached_settings: PipelineSettings | None = None

    @classmethod
    def get_settings(cls) -> PipelineSettings:
        """Get cached pipeline settings instance."""
        if cls._cached_settings is None:
            cls._cached_settings = build_pipeline_settings(get_settings())
        return cls._cached_settings

    @classmethod
    def reset_cache(cls) -> None:
        """Reset pipeline settings cache (for testing)."""
        cls._cached_settings = None


def get_pipeline_settings() -> PipelineSettings:
    """Get cached pipeline settings instance."""
    return PipelineConfigManager.get_settings()

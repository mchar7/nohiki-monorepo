"""Configuration management for job-correlation-evaluation-service."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings, Topics
from nohiki_ml_manifest import (
    FEATURE_COUNT,
    ManifestCache,
    ManifestMixin,
    SemanticRepresentationManifest,
)
from nohiki_qdrant_client import QdrantMixin
from nohiki_redis_utils import CachingSettings, RedisMixin
from nohiki_s3_client import S3Mixin
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict


class L2RModelSettings(BaseModel):
    """Configuration for L2R (Learning-to-Rank) model.

    Used for fail-fast validation at startup. If the loaded model's feature count
    doesn't match expected_feature_count, the service fails immediately.
    Calibrator type is validated from the artifact itself (self-describing dict),
    not from configuration.
    """

    model_path: Path = Field(
        default=Path("/app/models/l2r_lightgbm.txt"),
        description="Path to LightGBM model file (.txt format)",
    )
    calibrator_path: Path = Field(
        default=Path("/app/models/calibrator.joblib"),
        description="Path to calibrator file (.joblib format)",
    )
    model_version: str = Field(
        default="v6.0.0",
        description="Model version for cache keys and logging",
    )
    expected_feature_count: int = Field(
        default=FEATURE_COUNT,
        ge=1,
        le=1000,
        description="Expected number of features in L2R model. Service fails if model doesn't match.",
    )


class MLSettings(BaseModel):
    """ML settings for L2R model configuration."""

    l2r: L2RModelSettings = Field(default_factory=L2RModelSettings)


class BackfillSettings(BaseModel):
    """Settings for profile backfill operations."""

    enabled: bool = Field(default=True)
    max_listings: int = Field(default=500, ge=1, le=1000)
    since_days: int = Field(default=30, ge=1, le=90)
    callback_topic: str = Field(default=Topics.JOB_CORRELATION_BACKFILL_LISTINGS)


class CorrelationCachingSettings(CachingSettings):
    """Extended caching settings for job-correlation-evaluation-service.

    Provides Redis-backed caching for:
    - Active profiles: Cached to reduce DB queries per job event
    - Skill relationships: Shared across pods for skill expansion
    - ML manifest: Consistent manifest across pods
    """

    active_profiles_ttl: int = Field(default=300, ge=1, description="Active profiles cache TTL (5 min)")
    skill_relationships_ttl: int = Field(default=3600, ge=1, description="Skill relationships cache TTL (1 hour)")
    manifest_ttl: int = Field(default=86400, ge=1, description="ML manifest cache TTL (24 hours)")


class Settings(
    RedisMixin,
    DatabaseMixin,
    KafkaMixin,
    S3Mixin,
    QdrantMixin,
    ManifestMixin,
    NohikiBaseSettings,
):
    """Job correlation evaluation service settings."""

    model_config = SettingsConfigDict(env_prefix="JOB_CORRELATION_EVAL_")

    service_name: str = "job-correlation-evaluation-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Listing Matcher Service"
    service_desc_friendly: str = "Service for matching jobs to user preferences"

    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(
                max_concurrent_handlers=5,
            ),
        )
    )
    ml: MLSettings = Field(default_factory=MLSettings)
    backfill: BackfillSettings = Field(default_factory=BackfillSettings)
    caching: CorrelationCachingSettings = Field(default_factory=CorrelationCachingSettings)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()


def get_manifest() -> SemanticRepresentationManifest:
    """Get the cached manifest via shared ManifestCache.

    Returns:
        Loaded semantic representation manifest.

    """
    return ManifestCache.get(get_settings().manifest_path)

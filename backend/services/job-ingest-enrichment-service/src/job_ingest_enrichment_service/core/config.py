"""Configuration management for job-ingest-enrichment-service."""

from __future__ import annotations

from functools import cache

from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from nohiki_llm_client import LLMMixin
from nohiki_ml_manifest import ManifestCache, ManifestMixin, SemanticRepresentationManifest
from nohiki_redis_utils import RedisMixin
from pydantic import BaseModel, Field, PositiveInt
from pydantic_settings import SettingsConfigDict


class ProcessingSettings(BaseModel):
    """Processing behavior settings."""

    max_retries: PositiveInt = Field(default=3)
    timeout_seconds: PositiveInt = Field(default=120)
    max_prompt_description_chars: PositiveInt = Field(default=50_000)
    max_prompt_field_chars: PositiveInt = Field(default=2_000)
    max_embedding_text_chars: PositiveInt = Field(default=50_000)
    max_listing_description_chars: PositiveInt = Field(default=500_000)


class RateLimitSettings(BaseModel):
    """Rate limiting settings for LLM enrichment."""

    enabled: bool = Field(default=True, description="Enable rate limiting for LLM calls")
    requests_per_window: PositiveInt = Field(
        default=30,
        description="Maximum requests per time window",
    )
    window_seconds: PositiveInt = Field(
        default=60,
        description="Time window in seconds",
    )


class Settings(DatabaseMixin, RedisMixin, KafkaMixin, LLMMixin, ManifestMixin, NohikiBaseSettings):
    """Job ingest enrichment service settings."""

    model_config = SettingsConfigDict(env_prefix="JOB_INGEST_ENRICHMENT_")

    service_name: str = "job-ingest-enrichment-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Listing Parser Service"
    service_desc_friendly: str = "Microservice for processing raw job data into structured format using LLM analysis"

    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)

    # Override Kafka consumer settings for long LLM processing
    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(
                max_poll_records=5,  # Pre-fetch small batches while handlers are busy
                max_poll_interval_ms=600000,  # 10 minutes for long processing
                max_concurrent_handlers=8,  # Headroom for LLM latency variance
            )
        )
    )


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

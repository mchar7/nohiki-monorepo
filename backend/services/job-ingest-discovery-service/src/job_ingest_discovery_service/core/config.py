"""Configuration management for job-ingest-discovery-service."""

from __future__ import annotations

from functools import cache

from nohiki_core_settings import NohikiBaseSettings, is_development
from nohiki_db_utils import DatabaseMixin, DatabaseSettings
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from nohiki_redis_utils import CachingSettings, ExternalAPIConfig, RedisMixin
from pydantic import BaseModel, Field, PositiveInt, SecretStr
from pydantic_settings import SettingsConfigDict


class JSearchSettings(BaseModel):
    """JSearch API provider settings."""

    api_key: SecretStr = Field(default=SecretStr(""))
    base_url: str = Field(default="https://api.openwebninja.com/jsearch")
    timeout_seconds: PositiveInt = Field(default=30)
    enabled: bool = Field(default=False)


class DiscoveryCachingSettings(CachingSettings):
    """Extended caching settings for job-ingest-discovery-service.

    Includes external API configurations for rate limiting and fallback state tracking.
    """

    jsearch_api: ExternalAPIConfig = Field(
        default_factory=lambda: ExternalAPIConfig(
            name="jsearch",
            requests_per_minute=10,
            requests_per_hour=1000,
            requests_per_day=5000,
            fallback_ttl_seconds=86400,
        )
    )

    job_cache_ttl_seconds: int = Field(
        default=3600,
        ge=1,
        description="TTL for cached job data",
    )

    dedup_ttl_seconds: int = Field(
        default=2592000,
        ge=1,
        description="TTL for deduplication cache (30 days default)",
    )


class ProviderFallbackSettings(BaseModel):
    """Provider fallback behavior settings."""

    enabled: bool = Field(default=True)
    rate_limit_wait_threshold_seconds: PositiveInt = Field(default=1800)
    error_duration_threshold_seconds: PositiveInt = Field(default=300)
    min_consecutive_errors: PositiveInt = Field(default=3)


class ProviderConfigSettings(BaseModel):
    """Individual provider configuration."""

    name: str
    enabled: bool = Field(default=True)
    priority: int = Field(default=100)
    sources: list[str] = Field(default_factory=list)
    fallback: ProviderFallbackSettings = Field(default_factory=ProviderFallbackSettings)


class ProviderRegistrySettings(BaseModel):
    """Provider registry configuration."""

    providers: list[ProviderConfigSettings] = Field(default_factory=list)


class DiscoverySettings(BaseModel):
    """Discovery behavior settings."""

    max_concurrent: PositiveInt = Field(default=10)
    timeout_seconds: PositiveInt = Field(default=30)
    rate_limit_delay_seconds: float = Field(default=1.0, ge=0.0)
    cache_ttl_seconds: PositiveInt = Field(default=3600)
    max_results_per_source: PositiveInt = Field(
        default_factory=lambda: 3 if is_development() else 25,
        description="Max results per source per keyword (3 in dev, 25 in prod)",
    )


class Settings(DatabaseMixin, RedisMixin, KafkaMixin, NohikiBaseSettings):
    """Job ingest discovery service settings."""

    model_config = SettingsConfigDict(env_prefix="JOB_INGEST_DISCOVERY_")

    service_name: str = "job-ingest-discovery-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Job Ingest Discovery Service"
    service_desc_friendly: str = "Discovers job listings from multiple sources"

    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(
                max_concurrent_handlers=3,
            ),
        )
    )
    database: DatabaseSettings = Field(default_factory=lambda: DatabaseSettings(schema="job_ingest_discovery_schema"))
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)
    jsearch: JSearchSettings = Field(default_factory=JSearchSettings)
    provider_registry: ProviderRegistrySettings = Field(default_factory=ProviderRegistrySettings)
    caching: DiscoveryCachingSettings = Field(default_factory=DiscoveryCachingSettings)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()

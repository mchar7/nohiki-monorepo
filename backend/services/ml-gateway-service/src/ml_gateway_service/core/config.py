"""Configuration for ml-gateway-service with provider pattern."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal

from nohiki_core_settings import NohikiBaseSettings
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from nohiki_ml_manifest import DEFAULT_MANIFEST_PATH, ManifestCache, SemanticRepresentationManifest
from nohiki_redis_utils import CachingSettings, ExternalAPIConfig, RedisMixin
from pydantic import BaseModel, Field, PositiveInt, SecretStr
from pydantic_settings import SettingsConfigDict


class ProviderFallbackSettings(BaseModel):
    """Fallback settings for a provider (dynamic strategy only)."""

    enabled: bool = Field(default=True)
    rate_limit_wait_threshold_seconds: PositiveInt = Field(default=1800)
    error_duration_threshold_seconds: PositiveInt = Field(default=300)
    min_consecutive_errors: PositiveInt = Field(default=3)


class ProviderConfigSettings(BaseModel):
    """Per-provider configuration."""

    name: str
    enabled: bool = Field(default=True)
    priority: int = Field(default=100, description="Lower = higher priority")
    fallback: ProviderFallbackSettings = Field(default_factory=ProviderFallbackSettings)


class ProviderRegistrySettings(BaseModel):
    """Provider registry configuration."""

    providers: list[ProviderConfigSettings] = Field(default_factory=list)
    routing_strategy: Literal["dynamic", "balancing", "explicit"] = Field(default="dynamic")
    explicit_provider_name: str | None = Field(default=None)


class ModalSettings(BaseModel):
    """Modal.com integration settings."""

    token_id: SecretStr | None = Field(default=None)
    token_secret: SecretStr | None = Field(default=None)
    app_name: str = Field(default="nohiki-ml-encoding")


class MLKafkaSettings(KafkaSettings):
    """Extended Kafka settings with ML-specific consumer groups."""

    consumer_group_embedding: str = Field(default="ml-gateway-embedding-primary")
    consumer_group_rerank: str = Field(default="ml-gateway-rerank-primary")
    consumer_group_batch_embedding: str = Field(default="ml-gateway-batch-embedding-primary")


class MLGatewayCachingSettings(CachingSettings):
    """Extended caching settings for ml-gateway-service.

    Includes provider health tracking configuration for fallback state.
    """

    qdrant_provider: ExternalAPIConfig = Field(
        default_factory=lambda: ExternalAPIConfig(
            name="qdrant",
            fallback_ttl_seconds=86400,
        )
    )

    embedding_provider: ExternalAPIConfig = Field(
        default_factory=lambda: ExternalAPIConfig(
            name="embedding",
            fallback_ttl_seconds=86400,
        )
    )

    provider_fallback_state_ttl_seconds: int = Field(
        default=86400,
        ge=1,
        description="TTL for provider fallback state in Redis",
    )


class Settings(RedisMixin, KafkaMixin, NohikiBaseSettings):
    """ML Gateway Service configuration."""

    model_config = SettingsConfigDict(env_prefix="ML_GATEWAY_")

    service_name: str = "ml-gateway-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "ML Gateway Service"
    service_desc_friendly: str = "ML compute routing gateway - routes requests to provider-specific Kafka topics"

    # Pure routing: no compute, high message throughput
    kafka: MLKafkaSettings = Field(
        default_factory=lambda: MLKafkaSettings(
            consumer=KafkaConsumerSettings(max_concurrent_handlers=20),
        )
    )
    caching: MLGatewayCachingSettings = Field(default_factory=MLGatewayCachingSettings)

    provider_registry: ProviderRegistrySettings = Field(default_factory=ProviderRegistrySettings)
    modal: ModalSettings = Field(default_factory=ModalSettings)
    manifest_path: Path = Field(
        default=DEFAULT_MANIFEST_PATH,
        description="Path to the semantic representation manifest JSON",
    )


@cache
def get_settings() -> Settings:
    """Get cached ml-gateway-service settings singleton.

    Returns:
        Configured settings instance.
    """
    return Settings()


def get_manifest() -> SemanticRepresentationManifest:
    """Get the cached manifest for ml-gateway-service via shared ManifestCache.

    Returns:
        Loaded semantic representation manifest.
    """
    return ManifestCache.get(get_settings().manifest_path)

"""Configuration for ml-compute-service service."""

from __future__ import annotations

from enum import StrEnum
from functools import cache
from pathlib import Path

from nohiki_core_settings import NohikiBaseSettings
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from nohiki_ml_manifest import ManifestCache, ManifestMixin, SemanticRepresentationManifest
from nohiki_redis_utils import CachingSettings, RedisMixin
from nohiki_s3_client import S3Mixin
from pydantic import BaseModel, Field, PositiveInt
from pydantic_settings import SettingsConfigDict

# BatchEmbeddingRequested item-count contract advertised by Kubernetes provider.
_KUBERNETES_MAX_BATCH_ITEMS = 100


class ComputeBackendConfig(StrEnum):
    """Compute backend configuration options."""

    CPU = "cpu"
    GPU = "gpu"
    AUTO = "auto"


class MLComputeCachingSettings(CachingSettings):
    """Extended caching settings for ml-compute-service."""

    colbert_token_ttl: int = Field(
        default=604800,
        ge=1,
        description="ColBERT token cache TTL in seconds (7 days - expensive to compute)",
    )


class ProcessingSettings(BaseModel):
    """ML processing configuration."""

    # Request admission is fixed to the Kubernetes provider's advertised capability.
    # ``inference_batch_size`` remains independent and controls native micro-batches.
    max_request_items: PositiveInt = Field(
        default=_KUBERNETES_MAX_BATCH_ITEMS,
        ge=_KUBERNETES_MAX_BATCH_ITEMS,
        le=_KUBERNETES_MAX_BATCH_ITEMS,
    )
    max_batch_text_bytes: PositiveInt = Field(default=1_000_000, ge=100_000, le=1_000_000)
    inference_batch_size: PositiveInt = Field(default=8, ge=1, le=64)
    timeout_seconds: PositiveInt = Field(default=300, ge=30, le=600)
    cache_dir: Path = Field(
        default=Path("/home/app/.cache"),
        description="Local directory for cached ML model artifacts",
    )
    compute_backend: ComputeBackendConfig = Field(
        default=ComputeBackendConfig.CPU,
        description="Compute backend: 'cpu' (default), 'gpu' (requires [gpu] extras), or 'auto' (detect)",
    )


class Settings(RedisMixin, KafkaMixin, S3Mixin, ManifestMixin, NohikiBaseSettings):
    """ML compute worker configuration."""

    model_config = SettingsConfigDict(env_prefix="ML_COMPUTE_")

    service_name: str = "ml-compute-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "ML Compute Worker"
    service_desc_friendly: str = "Kubernetes ML compute worker using nohiki-ml-core"

    # CPU-bound embedding work: limit concurrency to avoid saturating the compute thread pool
    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(max_concurrent_handlers=2),
        )
    )

    caching: MLComputeCachingSettings = Field(default_factory=MLComputeCachingSettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)


@cache
def get_settings() -> Settings:
    """Get cached ml-compute-service settings singleton.

    Returns:
        Configured settings instance.
    """
    return Settings()


def get_manifest() -> SemanticRepresentationManifest:
    """Get the cached manifest for ml-compute-service via shared ManifestCache.

    Returns:
        Loaded semantic representation manifest.
    """
    return ManifestCache.get(get_settings().manifest_path)

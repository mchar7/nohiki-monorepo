"""Configuration management for job-storage-service."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from nohiki.ml.v1 import EntityType
from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from nohiki_ml_manifest import DEFAULT_MANIFEST_PATH, ManifestCache, ManifestMixin, SemanticRepresentationManifest
from nohiki_qdrant_client import QdrantMixin, QdrantVectorClient
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import SettingsConfigDict


def _resolve_default_manifest_path() -> Path:
    """Resolve the manifest path package-aware, independent of process cwd.

    ``ManifestMixin``'s default is relative to the repo root, which only
    resolves when the process cwd happens to be the repo root. Walk up from
    this file (not cwd) to find it instead, so it works the same from a
    package-scoped test runner as from a repo-root process.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / DEFAULT_MANIFEST_PATH
        if candidate.is_file():
            return candidate
    return DEFAULT_MANIFEST_PATH


class BackfillSettings(BaseModel):
    """Settings for backfill operations."""

    default_max_listings: int = Field(default=500, ge=1, le=1000)
    default_since_days: int = Field(default=30, ge=1, le=90)
    batch_size: int = Field(default=50, ge=10, le=100)


class Settings(ManifestMixin, QdrantMixin, DatabaseMixin, KafkaMixin, NohikiBaseSettings):
    """Job storage service settings."""

    model_config = SettingsConfigDict(env_prefix="JOB_STORAGE_")

    service_name: str = "job-storage-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Listing Store Service"
    service_desc_friendly: str = "Canonical storage and query interface for all processed job data"

    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(
                max_concurrent_handlers=15,
            ),
        )
    )
    backfill: BackfillSettings = Field(default_factory=BackfillSettings)

    @model_validator(mode="before")
    @classmethod
    def _apply_default_manifest_path(cls, data: dict[str, object]) -> dict[str, object]:
        """Fill in a package-aware default when no override was supplied.

        Runs before ``ManifestMixin``'s cwd-relative default and its
        existence check, but after env vars / explicit kwargs are merged, so
        ``JOB_STORAGE_MANIFEST_PATH`` (or an explicit ``manifest_path=``)
        still wins.
        """
        if not data.get("manifest_path"):
            data["manifest_path"] = _resolve_default_manifest_path()
        return data


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()


def get_manifest() -> SemanticRepresentationManifest:
    """Load the semantic representation manifest shared by vector producers and consumers."""
    return ManifestCache.get(get_settings().manifest_path)


def get_jobs_collection_name() -> str:
    """Return the manifest-owned job collection name."""
    return get_manifest().get_collection_name(EntityType.JOB)


@cache
def get_qdrant_client() -> QdrantVectorClient:
    """Construct the schema-aware job vector lifecycle client."""
    settings = get_settings()
    return QdrantVectorClient(settings.qdrant, get_manifest().collections.jobs.qdrant)

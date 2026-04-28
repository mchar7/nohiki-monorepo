"""Configuration management for user-pref-service."""

from __future__ import annotations

from functools import cache

from nohiki.ml.v1 import EntityType
from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin, DatabaseSettings
from nohiki_kafka_client import KafkaMixin
from nohiki_ml_manifest import ManifestCache, ManifestMixin, SemanticRepresentationManifest
from nohiki_qdrant_client import QdrantMixin, QdrantVectorClient
from nohiki_redis_utils import RedisMixin
from pydantic import Field, PositiveInt
from pydantic_settings import SettingsConfigDict


class Settings(DatabaseMixin, KafkaMixin, RedisMixin, ManifestMixin, QdrantMixin, NohikiBaseSettings):
    """User pref service settings."""

    model_config = SettingsConfigDict(env_prefix="USER_PREF_")

    service_name: str = "user-pref-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "User Pref Service"
    service_desc_friendly: str = "Job target profile management for Nohiki platform"

    database: DatabaseSettings = Field(default_factory=lambda: DatabaseSettings(schema="user_pref_schema"))
    max_keywords: PositiveInt = Field(default=50)
    max_locations: PositiveInt = Field(default=20)

    skill_normalization_enabled: bool = Field(default=True)
    geocoding_enabled: bool = Field(default=True)


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


def get_profiles_collection_name() -> str:
    """Return the manifest-owned profile collection name."""
    return get_manifest().get_collection_name(EntityType.PROFILE)


@cache
def get_qdrant_client() -> QdrantVectorClient:
    """Construct the schema-aware profile vector lifecycle client."""
    settings = get_settings()
    return QdrantVectorClient(settings.qdrant, get_manifest().collections.profiles.qdrant)

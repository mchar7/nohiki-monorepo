"""Configuration management for job-query-composition-service."""

from __future__ import annotations

from functools import cache

from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin, DatabaseSettings
from nohiki_kafka_client import KafkaMixin
from nohiki_redis_utils import RedisMixin
from pydantic import BaseModel, Field, PositiveInt
from pydantic_settings import SettingsConfigDict


class CompositionSettings(BaseModel):
    """Query composition behavior settings."""

    inactivity_threshold_days: PositiveInt = Field(default=30)


class Settings(DatabaseMixin, RedisMixin, KafkaMixin, NohikiBaseSettings):
    """Job query composition service settings."""

    model_config = SettingsConfigDict(env_prefix="JOB_QUERY_COMPOSITION_")

    service_name: str = "job-query-composition-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Query Composer Service"
    service_desc_friendly: str = "Clusters user profiles into deduplicated scrape queries"

    database: DatabaseSettings = Field(default_factory=lambda: DatabaseSettings(schema="job_query_schema"))
    composition: CompositionSettings = Field(default_factory=CompositionSettings)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()

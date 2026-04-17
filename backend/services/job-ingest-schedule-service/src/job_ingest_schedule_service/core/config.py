"""Configuration management for job-ingest-schedule-service."""

from __future__ import annotations

from functools import cache

from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin, DatabaseSettings
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from pydantic import BaseModel, Field, PositiveInt
from pydantic_settings import SettingsConfigDict


class SchedulerSettings(BaseModel):
    """Scheduler behavior settings."""

    default_hours_old: PositiveInt = Field(default=72)
    default_results_wanted: PositiveInt = Field(default=50)
    batch_limit: PositiveInt = Field(default=100)


class Settings(DatabaseMixin, KafkaMixin, NohikiBaseSettings):
    """Job ingest schedule service settings."""

    model_config = SettingsConfigDict(env_prefix="JOB_INGEST_SCHEDULE_")

    service_name: str = "job-ingest-schedule-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Scrape Scheduler Service"
    service_desc_friendly: str = "Triggers scrapes at the right time based on query frequency"

    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(
                max_concurrent_handlers=5,
            ),
        )
    )
    database: DatabaseSettings = Field(default_factory=lambda: DatabaseSettings(schema="job_schedule_schema"))
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()

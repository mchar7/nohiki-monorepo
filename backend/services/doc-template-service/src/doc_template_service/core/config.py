"""Configuration management for doc-template-service."""

from __future__ import annotations

from functools import cache

from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from nohiki_redis_utils import RedisMixin
from nohiki_s3_client import S3Mixin
from pydantic import BaseModel, Field, PositiveInt
from pydantic_settings import SettingsConfigDict


class GotenbergSettings(BaseModel):
    """Gotenberg PDF service settings."""

    base_url: str = Field(default="http://gotenberg:3000")
    request_timeout_s: int = Field(default=10, ge=1)


class TemplateServiceSettings(BaseModel):
    """Template service specific settings."""

    cache_max_items: PositiveInt = Field(default=1000)
    cache_ttl_seconds: PositiveInt = Field(default=3600)
    seed_on_startup: bool = Field(default=True)
    db_search_path: str = Field(default="doc_template_schema,public")


class Settings(DatabaseMixin, RedisMixin, KafkaMixin, S3Mixin, NohikiBaseSettings):
    """Doc template service settings."""

    model_config = SettingsConfigDict(env_prefix="DOC_TEMPLATE_")

    service_name: str = "doc-template-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Doc Template Service"
    service_desc_friendly: str = "Generate visually rich documents from templates"

    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(
                max_concurrent_handlers=5,
            ),
        )
    )
    gotenberg: GotenbergSettings = Field(default_factory=GotenbergSettings)
    template_settings: TemplateServiceSettings = Field(default_factory=TemplateServiceSettings)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()

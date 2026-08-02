"""Configuration management for doc-content-service."""

from __future__ import annotations

from functools import cache

from nohiki_core_settings import NohikiBaseSettings
from nohiki_kafka_client import KafkaMixin
from nohiki_llm_client import LLMMixin
from nohiki_s3_client import S3Mixin
from pydantic import BaseModel, Field, PositiveInt
from pydantic_settings import SettingsConfigDict


class GenerationSettings(BaseModel):
    """Content generation processing settings."""

    timeout_seconds: PositiveInt = Field(default=120)
    max_retry_attempts: PositiveInt = Field(default=3)
    max_attachments: PositiveInt = Field(default=20)
    max_attachment_bytes: PositiveInt = Field(default=1_000_000)
    max_total_attachment_bytes: PositiveInt = Field(default=5_000_000)
    max_schema_bytes: PositiveInt = Field(default=1_000_000)
    max_prompt_characters: PositiveInt = Field(default=1_000_000)
    max_cached_agents: PositiveInt = Field(default=100)


class Settings(LLMMixin, KafkaMixin, S3Mixin, NohikiBaseSettings):
    """Doc content service settings."""

    model_config = SettingsConfigDict(env_prefix="DOC_CONTENT_")

    service_name: str = "doc-content-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Document Content Service"
    service_desc_friendly: str = "Prepares schema-constrained job-application drafts with an LLM for user review"

    generation: GenerationSettings = Field(default_factory=GenerationSettings)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()

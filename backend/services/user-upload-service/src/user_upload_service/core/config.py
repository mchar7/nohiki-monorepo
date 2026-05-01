"""Configuration management for user-upload-service."""

from functools import cache

from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaMixin
from nohiki_s3_client import S3Mixin
from pydantic import BaseModel, Field, PositiveInt
from pydantic_settings import SettingsConfigDict


class UploadSettings(BaseModel):
    """Upload behavior settings."""

    max_size_mb: PositiveInt = Field(default=10)

    @property
    def max_size_bytes(self) -> int:
        """Get max upload size in bytes."""
        return self.max_size_mb * 1024 * 1024


class Settings(DatabaseMixin, KafkaMixin, S3Mixin, NohikiBaseSettings):
    """User upload service settings."""

    model_config = SettingsConfigDict(env_prefix="USER_UPLOAD_")

    service_name: str = "user-upload-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Upload Service"
    service_desc_friendly: str = "Document storage with S3/MinIO backend for Nohiki platform"

    upload: UploadSettings = Field(default_factory=UploadSettings)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()

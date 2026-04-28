"""Configuration management for user-entitlement-service."""

from __future__ import annotations

from functools import cache

from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaMixin
from pydantic_settings import SettingsConfigDict


class Settings(DatabaseMixin, KafkaMixin, NohikiBaseSettings):
    """User entitlement service settings."""

    model_config = SettingsConfigDict(env_prefix="USER_ENTITLEMENT_")

    service_name: str = "user-entitlement-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Entitlements Service"
    service_desc_friendly: str = "Account entitlements and tier management for Nohiki platform"


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()

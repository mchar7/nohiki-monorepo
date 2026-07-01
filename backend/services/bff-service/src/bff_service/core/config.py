"""Configuration management for bff-service."""

from __future__ import annotations

from functools import cache
from typing import Literal

from nohiki_core_settings import NohikiBaseSettings
from nohiki_core_settings.env import is_development
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from nohiki_redis_utils import (
    CachingSettings,
    RedisMixin,
)
from nohiki_s3_client import S3Mixin
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict


class JWTSettings(BaseModel):
    """JWT/JWKS configuration."""

    jwks_url: str = Field(default="", description="JWKS endpoint URL")
    issuer: str = Field(default="https://api.nohiki.com")
    audience: str = Field(default="https://app.nohiki.com")


def _get_default_cookie_name(name: str) -> str:
    """Get cookie name with __Host- prefix only in production (HTTPS required)."""
    if is_development():
        return name
    return f"__Host-{name}"


class CookieSettings(BaseModel):
    """Cookie configuration.

    Note: __Host- prefix requires HTTPS and is only used in production.
    In development, plain cookie names are used for HTTP compatibility.
    """

    access_token_name: str = Field(default_factory=lambda: _get_default_cookie_name("nohiki_at"))
    secure: bool = Field(default_factory=lambda: not is_development())
    samesite: Literal["lax", "strict", "none"] = Field(default="lax")


class OriginSettings(BaseModel):
    """CORS and CSRF origin configuration."""

    cors_origins: str = Field(default="", description="Comma-separated CORS allowed origins")
    csrf_origins: str = Field(default="", description="Comma-separated CSRF allowed origins")

    def get_cors_origins(self) -> list[str]:
        """Get CORS allowed origins as a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def get_csrf_origins(self) -> list[str]:
        """Get CSRF allowed origins as a list."""
        return [o.strip() for o in self.csrf_origins.split(",") if o.strip()]


DEV_AUTH_PER_MINUTE = 10000
DEV_AUTH_PER_HOUR = 100000
DEV_ANON_PER_MINUTE = 10000
DEV_ANON_PER_HOUR = 100000
DEV_SENSITIVE_PER_MINUTE = 1000

PROD_AUTH_PER_MINUTE = 120
PROD_AUTH_PER_HOUR = 3000
PROD_ANON_PER_MINUTE = 30
PROD_ANON_PER_HOUR = 300
PROD_SENSITIVE_PER_MINUTE = 10


def _env_default(dev_val: int, prod_val: int) -> int:
    """Return dev or prod value based on environment at call time."""
    return dev_val if is_development() else prod_val


class BFFRateLimitConfig(BaseModel):
    """Rate limit config for BFF service with environment-aware defaults.

    Defined as a standalone model (not extending RateLimitSettings) to avoid
    ty's invariant mutable field override error on CachingSettings.rate_limit.
    """

    enabled: bool = Field(default=True, description="Enable rate limiting")
    requests_per_window: int = Field(default=100, ge=1, description="Max requests per window")
    window_seconds: int = Field(default=60, ge=1, description="Rate limit window in seconds")
    key_prefix: str = Field(default="ratelimit", description="Redis key prefix")
    auth_requests_per_minute: int = Field(
        default_factory=lambda: _env_default(DEV_AUTH_PER_MINUTE, PROD_AUTH_PER_MINUTE),
        ge=1,
    )
    auth_requests_per_hour: int = Field(
        default_factory=lambda: _env_default(DEV_AUTH_PER_HOUR, PROD_AUTH_PER_HOUR),
        ge=1,
    )
    anon_requests_per_minute: int = Field(
        default_factory=lambda: _env_default(DEV_ANON_PER_MINUTE, PROD_ANON_PER_MINUTE),
        ge=1,
    )
    anon_requests_per_hour: int = Field(
        default_factory=lambda: _env_default(DEV_ANON_PER_HOUR, PROD_ANON_PER_HOUR),
        ge=1,
    )
    sensitive_requests_per_minute: int = Field(
        default_factory=lambda: _env_default(DEV_SENSITIVE_PER_MINUTE, PROD_SENSITIVE_PER_MINUTE),
        ge=1,
    )


class BFFCachingSettings(CachingSettings):
    """Extended caching settings for BFF service."""

    search_results_ttl: int = Field(default=120, ge=1, description="Search results cache TTL (2 min)")
    bff_rate_limit: BFFRateLimitConfig = Field(default_factory=BFFRateLimitConfig)


class SSESettings(BaseModel):
    """SSE stream configuration."""

    heartbeat_interval_seconds: int = Field(default=10, ge=1, description="Ping interval for SSE keepalive")
    max_stream_duration_seconds: int = Field(
        default=600,
        ge=1,
        description="Max SSE stream duration before server-side close",
    )
    reconnect_interval_ms: int = Field(default=5000, ge=1000, description="EventSource retry interval sent to client")
    stale_cutoff_hours: int = Field(
        default=24,
        ge=1,
        description="Ignore documents older than this for initial dump",
    )
    initial_replay_limit: int = Field(default=100, ge=1, le=1000, description="Maximum initial events per stream")
    max_concurrent_streams_per_user: int = Field(
        default=3, ge=1, le=20, description="Maximum concurrent SSE streams per user"
    )


class AuthListingsSettings(BaseModel):
    """Environment-configurable settings for the auth-listings endpoint.

    All values have safe defaults for development. In production,
    ``secret`` must be set via ``BFF_AUTH_LISTINGS__SECRET``.

    Attributes:
        secret: Shared HMAC secret for Worker authentication. Empty in dev.
        max_listing_age_days: Maximum age of listings to include.
        min_title_length: Minimum title length to filter low-quality listings.
        primary_candidate_limit: Max rows fetched for same-country query.
        backfill_candidate_limit: Max rows fetched for backfill query.
        backfill_threshold: Trigger backfill when primary count is below this.
        max_listings_returned: Final response size cap after diversity filter.
        max_per_company: Max listings per company in the diversity filter.
        rate_limit_per_minute: Per-route rate limit for auth-listings requests.
    """

    secret: str = Field(default="", description="Shared secret for Worker auth. Required in production.")
    max_listing_age_days: int = Field(default=30, ge=1, le=90)
    min_title_length: int = Field(default=10, ge=1, le=100)
    primary_candidate_limit: int = Field(default=500, ge=50, le=2000)
    backfill_candidate_limit: int = Field(default=300, ge=50, le=1000)
    backfill_threshold: int = Field(default=30, ge=5, le=100)
    max_listings_returned: int = Field(default=150, ge=10, le=500)
    max_per_company: int = Field(default=5, ge=1, le=50)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=1000)


class Settings(DatabaseMixin, RedisMixin, KafkaMixin, S3Mixin, NohikiBaseSettings):
    """BFF service settings."""

    model_config = SettingsConfigDict(env_prefix="BFF_")

    service_name: str = "bff-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "BFF Service"
    service_desc_friendly: str = "Backend-for-Frontend - unified browser API with CQRS projections"

    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(
                max_concurrent_handlers=20,
            ),
        )
    )
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    cookie: CookieSettings = Field(default_factory=CookieSettings)
    origins: OriginSettings = Field(default_factory=OriginSettings)
    caching: BFFCachingSettings = Field(default_factory=BFFCachingSettings)
    sse: SSESettings = Field(default_factory=SSESettings)
    auth_listings: AuthListingsSettings = Field(default_factory=AuthListingsSettings)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()

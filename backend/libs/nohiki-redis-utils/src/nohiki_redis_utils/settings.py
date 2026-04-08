"""Redis configuration settings, caching settings, and mixin for Nohiki services.

Naming convention: ``*Settings`` = Pydantic env-var configurable model,
``*Config`` = runtime dataclass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from nohiki_core_settings import DEVELOPMENT_ENVIRONMENTS, SettingsMixin
from pydantic import BaseModel, Field, RedisDsn, TypeAdapter, model_validator

if TYPE_CHECKING:
    from typing import Self

_redis_dsn_adapter: TypeAdapter[RedisDsn] = TypeAdapter(RedisDsn)
_default_redis_dsn: RedisDsn = _redis_dsn_adapter.validate_python("redis://localhost:6379")


class RedisSettings(BaseModel):
    """Redis configuration (DSN-only).

    Provide a complete connection string via ``dsn``.
    Use ``rediss://`` scheme for SSL connections.
    """

    dsn: RedisDsn = Field(
        default=_default_redis_dsn,
        description="Redis connection string (redis:// or rediss://)",
    )

    socket_timeout: float = Field(default=5.0, gt=0)
    socket_connect_timeout: float = Field(default=5.0, gt=0)
    retry_on_timeout: bool = Field(default=True)
    max_connections: int = Field(default=10, ge=1, le=100)

    default_ttl_seconds: int = Field(default=3600, ge=1)

    @property
    def connection_string(self) -> str:
        """Get connection string."""
        return str(self.dsn)


class CacheKeyConfig(BaseModel):
    """Configuration for a cache key pattern."""

    prefix: str = Field(..., description="Key prefix (e.g., 'profile', 'user')")
    separator: str = Field(default=":", description="Separator between key parts")

    def build(self, *parts: str) -> str:
        """Build cache key from parts."""
        return self.separator.join([self.prefix, *parts])


class CacheTTLConfig(BaseModel):
    """TTL configuration with semantic presets.

    All values in seconds. Configure via environment variables:
        CACHING__TTLS__SHORT=300
        CACHING__TTLS__PROJECTION=86400
    """

    short: int = Field(default=300, ge=1, description="Short TTL (5 min) - volatile data")
    medium: int = Field(default=3600, ge=1, description="Medium TTL (1 hour) - session data")
    long: int = Field(default=86400, ge=1, description="Long TTL (24 hours) - stable data")

    projection: int = Field(default=86400, ge=1, description="Projection/ledger cache TTL")
    rate_limit_window: int = Field(default=60, ge=1, description="Rate limit window TTL")
    circuit_breaker: int = Field(default=300, ge=1, description="Circuit breaker state TTL")
    token: int = Field(default=3600, ge=1, description="Token/session cache TTL")
    fallback_state: int = Field(default=86400, ge=1, description="Provider fallback state TTL")


class RateLimitSettings(BaseModel):
    """Rate limiting configuration (settings layer).

    Configure via environment variables:
        CACHING__RATE_LIMIT__ENABLED=true
        CACHING__RATE_LIMIT__REQUESTS_PER_WINDOW=100
    """

    enabled: bool = Field(default=True, description="Enable rate limiting")
    requests_per_window: int = Field(default=100, ge=1, description="Max requests per window")
    window_seconds: int = Field(default=60, ge=1, description="Rate limit window in seconds")
    key_prefix: str = Field(default="ratelimit", description="Redis key prefix")

    def build_key(self, identifier: str) -> str:
        """Build rate limit key for identifier (user_id, IP, etc.)."""
        return f"{self.key_prefix}:{identifier}"


class CircuitBreakerSettings(BaseModel):
    """Circuit breaker configuration (settings layer).

    Configure via environment variables:
        CACHING__CIRCUIT_BREAKER__FAILURE_THRESHOLD=5
        CACHING__CIRCUIT_BREAKER__TIMEOUT_SECONDS=30
    """

    enabled: bool = Field(default=True, description="Enable circuit breaker")
    failure_threshold: int = Field(default=5, ge=1, description="Failures before opening circuit")
    success_threshold: int = Field(default=2, ge=1, description="Successes to close circuit")
    timeout_seconds: int = Field(default=30, ge=1, description="Time in open state before half-open")
    half_open_max_calls: int = Field(default=3, ge=1, description="Max calls in half-open state")
    key_prefix: str = Field(default="circuit", description="Redis key prefix")

    def build_state_key(self, circuit_name: str) -> str:
        """Build circuit breaker state key."""
        return f"{self.key_prefix}:{circuit_name}:state"

    def build_failure_count_key(self, circuit_name: str) -> str:
        """Build circuit breaker failure count key."""
        return f"{self.key_prefix}:{circuit_name}:failures"


class ExternalAPIConfig(BaseModel):
    """Configuration for external API rate limiting.

    Used for services that call external APIs (JSearch, OpenAI, etc.)
    with strict quotas that must be respected across all pods.
    """

    name: str = Field(..., description="API name (e.g., 'jsearch', 'openai')")
    requests_per_minute: int = Field(default=60, ge=1, description="Requests per minute")
    requests_per_hour: int = Field(default=1000, ge=1, description="Requests per hour")
    requests_per_day: int = Field(default=10000, ge=1, description="Requests per day")
    fallback_ttl_seconds: int = Field(default=86400, ge=1, description="Fallback state TTL")

    def rate_limit_key(self, tier: str) -> str:
        """Build rate limit key for tier.

        Args:
            tier: One of 'minute', 'hour', 'day'.

        Returns:
            Redis key for the rate limit counter.

        """
        return f"api:{self.name}:ratelimit:{tier}"

    def fallback_key(self) -> str:
        """Build fallback state key."""
        return f"api:{self.name}:fallback"

    def health_key(self) -> str:
        """Build provider health state key."""
        return f"api:{self.name}:health"


class CachingSettings(BaseModel):
    """caching configuration for a service.

    This is the main configuration class that services should use.
    It provides standardized TTLs, rate limiting, and circuit breaker settings.

    Usage in config.py::

        class Settings(NohikiBaseSettings, RedisMixin):
            caching: CachingSettings = Field(default_factory=CachingSettings)

    Services can extend this with additional key configurations::

        class MyCachingSettings(CachingSettings):
            profile_key: CacheKeyConfig = CacheKeyConfig(prefix="profile")

    Environment variable configuration::

        CACHING__TTLS__PROJECTION=3600
        CACHING__RATE_LIMIT__REQUESTS_PER_WINDOW=200
        CACHING__CIRCUIT_BREAKER__FAILURE_THRESHOLD=10
    """

    ttls: CacheTTLConfig = Field(default_factory=CacheTTLConfig)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    circuit_breaker: CircuitBreakerSettings = Field(default_factory=CircuitBreakerSettings)
    global_prefix: str = Field(default="", description="Global prefix for all cache keys")
    separator: str = Field(default=":", description="Default separator for cache keys")

    def build_key(self, *parts: str) -> str:
        """Build a cache key from parts.

        Args:
            *parts: Key parts to join with separator.

        Returns:
            Complete cache key, optionally with global prefix.

        Example::

            settings.caching.build_key("user", user_id, "profile")
            # Returns: "user:abc123:profile" or "myservice:user:abc123:profile"

        """
        key = self.separator.join(parts)
        if self.global_prefix:
            return f"{self.global_prefix}{self.separator}{key}"
        return key

    model_config = {"extra": "allow"}


class RedisMixin(SettingsMixin):
    """Mixin that declares redis as required. Combine with NohikiBaseSettings.

    Provides SSL enforcement via model validator and enables Redis OTEL
    instrumentation via the ``instrument_redis`` property (overrides the
    default ``False`` from NohikiBaseSettings).

    Usage::

        class Settings(RedisMixin, NohikiBaseSettings):
            model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")
    """

    redis: RedisSettings = Field(default_factory=RedisSettings)

    @model_validator(mode="after")
    def _validate_redis_ssl(self) -> Self:
        """Enforce rediss:// scheme in non-development environments."""
        dsn_str = str(self.redis.dsn)
        if self.environment not in DEVELOPMENT_ENVIRONMENTS and not dsn_str.startswith("rediss://"):
            msg = "Redis must use rediss:// (SSL) in production"
            raise ValueError(msg)
        return self

    @property
    def redis_url(self) -> str:
        """Get Redis connection string."""
        return self.redis.connection_string

    @property
    def instrument_redis(self) -> bool:
        """Override NohikiBaseSettings default: enable Redis OTEL instrumentation."""
        return True


@runtime_checkable
class HasRedisSettings(Protocol):
    """Protocol for settings objects that have Redis configuration."""

    @property
    def redis(self) -> RedisSettings:
        """Redis configuration settings."""
        ...

    @property
    def service_name(self) -> str:
        """Service name for identification."""
        ...

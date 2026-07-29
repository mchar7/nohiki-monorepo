"""Configuration management for notification-service."""

from __future__ import annotations

from functools import cache
from typing import Literal

import httpx
from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from nohiki_redis_utils import RedisMixin
from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, SecretStr
from pydantic_settings import SettingsConfigDict


class ProviderTimeoutSettings(BaseModel):
    """Per-phase httpx timeout budget for outbound provider calls.

    A single flat timeout lets a slow connect consume the whole budget and
    starve the response phase. Splitting it per phase also bounds how long one
    hung provider can hold an outbox worker.
    """

    connect_seconds: PositiveFloat = Field(default=5.0)
    read_seconds: PositiveFloat = Field(default=15.0)
    write_seconds: PositiveFloat = Field(default=10.0)
    pool_seconds: PositiveFloat = Field(default=5.0)

    def to_httpx_timeout(self) -> httpx.Timeout:
        """Build the equivalent :class:`httpx.Timeout`.

        Returns:
            Timeout carrying an explicit budget for every request phase.

        """
        return httpx.Timeout(
            connect=self.connect_seconds,
            read=self.read_seconds,
            write=self.write_seconds,
            pool=self.pool_seconds,
        )


class EmailSettings(BaseModel):
    """Email provider settings."""

    provider: Literal["resend", "twilio_sendgrid"] = Field(default="resend")
    api_key: SecretStr = Field(default=SecretStr(""))
    from_address: str = Field(default="noreply@nohiki.com")
    from_name: str = Field(default="Nohiki")
    unsubscribe_domain: str = Field(default="nohiki.com")
    timeout: ProviderTimeoutSettings = Field(default_factory=ProviderTimeoutSettings)


class OutboxSettings(BaseModel):
    """Outbox processing settings.

    ``poll_interval_sec`` caps how long the worker sleeps between polls when
    the queue is empty. ``error_backoff_seconds`` only kicks in after a
    loop-level exception (DB outage etc.); per-message errors go through
    ``RetryStrategy``. ``batch_size`` caps messages per poll; each one runs
    in its own short transaction so the size has no effect on lock duration.

    ``jitter_factor`` scatters retry timing across pods. Without it, a fleet
    of workers that fail at the same instant retries in lockstep and can
    re-trip the provider's circuit breaker on its HALF_OPEN probe.
    """

    poll_interval_sec: PositiveInt = Field(default=5)
    max_retries: PositiveInt = Field(default=3)
    retry_backoff_multiplier: PositiveInt = Field(default=2)
    retry_base_delay_seconds: PositiveInt = Field(default=5)
    max_retry_delay_seconds: PositiveInt = Field(default=300)
    batch_size: PositiveInt = Field(default=10)
    error_backoff_seconds: PositiveInt = Field(
        default=5,
        description="Sleep after an unhandled loop exception to avoid CPU spin.",
    )
    jitter_factor: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description=(
            "Symmetric jitter applied to retry backoff as a fraction of the "
            "computed delay. 0 disables jitter; 0.2 means each scheduled "
            "retry is uniformly perturbed in [-20%, +20%]."
        ),
    )


class RateLimitSettings(BaseModel):
    """Rate limiting settings."""

    requests_per_window: PositiveInt = Field(default=10)
    window_seconds: PositiveInt = Field(default=60)


class CircuitBreakerSettings(BaseModel):
    """Per-provider circuit-breaker settings used by ``ProviderRouter``.

    The breaker short-circuits a misbehaving provider so traffic can flow
    through its siblings. State is in-process only; a pod restart resets all
    breakers, which is fine because they're a load-shedding optimisation, not
    a correctness primitive.
    """

    failure_threshold: PositiveInt = Field(
        default=5,
        description="Consecutive failures before CLOSED -> OPEN.",
    )
    success_threshold: PositiveInt = Field(
        default=2,
        description="Consecutive HALF_OPEN successes before returning to CLOSED.",
    )
    timeout_seconds: PositiveFloat = Field(
        default=30.0,
        description="Time spent OPEN before the first HALF_OPEN probe is allowed.",
    )
    half_open_max_calls: PositiveInt = Field(
        default=1,
        description="Concurrent probes allowed while HALF_OPEN.",
    )


class FrequencyCapSettings(BaseModel):
    """Per-user notification frequency cap.

    State lives in Redis, not in the pod: the cap has to hold across a restart
    and across every replica, and the Redis token bucket decides atomically in
    one round trip. ``max_per_window`` is also the burst size, so a user who
    has been quiet can receive a full window's worth at once and is then held
    to the refill rate.
    """

    enabled: bool = Field(default=True)
    max_per_window: PositiveInt = Field(
        default=5,
        description="Notifications admitted per user per window.",
    )
    window_seconds: PositiveInt = Field(
        default=3600,
        description="Window the cap refills over.",
    )


class MessageTTLSettings(BaseModel):
    """Message expiry and sweep settings.

    A queued notification that is hours stale is worse than no notification,
    and unswept rows keep widening the partial queue index. The sweep cancels
    them a batch at a time and publishes each expiry as a lifecycle event; the
    worker re-checks expiry before every send to close the gap between claiming
    a row and dispatching it.
    """

    default_ttl_hours: PositiveInt = Field(
        default=24,
        description="Lifetime stamped onto ``expires_at`` at message creation.",
    )
    sweep_interval_seconds: PositiveInt = Field(
        default=300,
        description="Seconds between sweep passes.",
    )
    sweep_batch_size: PositiveInt = Field(
        default=500,
        description="Maximum rows cancelled per sweep pass.",
    )


class Settings(DatabaseMixin, RedisMixin, KafkaMixin, NohikiBaseSettings):
    """Notification service settings."""

    model_config = SettingsConfigDict(env_prefix="NOTIFICATION_")

    service_name: str = "notification-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Notification Service"
    service_desc_friendly: str = "Service for managing and sending messages via various providers"

    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(
                max_concurrent_handlers=5,
            ),
        )
    )
    email: EmailSettings = Field(default_factory=EmailSettings)
    outbox: OutboxSettings = Field(default_factory=OutboxSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    circuit_breaker: CircuitBreakerSettings = Field(default_factory=CircuitBreakerSettings)
    frequency_cap: FrequencyCapSettings = Field(default_factory=FrequencyCapSettings)
    message_ttl: MessageTTLSettings = Field(default_factory=MessageTTLSettings)

    start_workers: bool = Field(default=True)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()


settings = get_settings()

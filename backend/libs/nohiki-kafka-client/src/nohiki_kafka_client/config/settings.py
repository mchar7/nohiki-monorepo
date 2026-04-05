"""Kafka configuration settings and mixin for Nohiki services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki_core_settings import DEVELOPMENT_ENVIRONMENTS, SettingsMixin
from pydantic import BaseModel, Field, KafkaDsn, SecretStr, TypeAdapter, model_validator

from nohiki_kafka_client.config.client_config import SaslMechanism, SecurityProtocol

if TYPE_CHECKING:
    from typing import Self

_kafka_dsn_adapter: TypeAdapter[KafkaDsn] = TypeAdapter(KafkaDsn)
_default_kafka_dsn: KafkaDsn = _kafka_dsn_adapter.validate_python("kafka://localhost:29092")


class KafkaSaslSettings(BaseModel):
    """SASL credentials and mechanism."""

    mechanism: SaslMechanism | None = None
    username: str | None = None
    password: SecretStr | None = None


class KafkaTlsSettings(BaseModel):
    """Optional client TLS material paths."""

    ca_location: str | None = None
    certificate_location: str | None = None
    key_location: str | None = None
    key_password: SecretStr | None = None


class KafkaSecuritySettings(BaseModel):
    """Kafka transport security settings."""

    protocol: SecurityProtocol = SecurityProtocol.PLAINTEXT
    sasl: KafkaSaslSettings = Field(default_factory=KafkaSaslSettings)
    tls: KafkaTlsSettings = Field(default_factory=KafkaTlsSettings)

    @model_validator(mode="after")
    def _validate_sasl_credentials(self) -> Self:
        if self.sasl.mechanism is SaslMechanism.OAUTHBEARER:
            msg = "OAUTHBEARER requires a configured token provider; environment settings do not support one"
            raise ValueError(msg)
        if self.protocol in {SecurityProtocol.SASL_PLAINTEXT, SecurityProtocol.SASL_SSL} and (
            self.sasl.mechanism is None or not self.sasl.username or not self.sasl.password
        ):
            msg = "SASL protocols require mechanism, username, and password"
            raise ValueError(msg)
        return self


class KafkaConsumerSettings(BaseModel):
    """Consumer-specific configuration."""

    max_poll_records: int = Field(
        default=500,
        description="Maximum records per poll (reduce for long-running handlers)",
    )
    max_poll_interval_ms: int = Field(
        default=300000,
        description="Max time between polls before consumer is removed from group",
    )
    session_timeout_ms: int = Field(
        default=30000,
        description="Broker marks consumer dead after this many ms without a heartbeat",
    )
    heartbeat_interval_ms: int = Field(
        default=3000,
        description="How often the consumer sends heartbeats to the broker",
    )
    max_concurrent_handlers: int = Field(
        default=10,
        ge=1,
        le=200,
        description=(
            "Maximum number of message handlers that may run concurrently per consumer group. "
            "Tune per service: CPU-bound workloads (ML compute) → 1-2; "
            "I/O-bound workloads (DB projections, pure routing) → 15-20."
        ),
    )


class ResilienceSettings(BaseModel):
    """Kafka message resilience configuration (retry + dead-letter queue).

    Controls how failed messages are retried and when they are routed to
    the dead-letter queue.  These defaults apply to all handlers in the
    service unless overridden per-handler via ``@kafka_client.with_resilience()``.

    Configurable via nested env vars, e.g.
    ``KAFKA__RESILIENCE__MAX_RETRIES=5``.
    """

    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retry attempts before routing to DLQ",
    )
    retry_backoff_ms: int = Field(
        default=1000,
        ge=0,
        description="Base backoff delay between retries (ms)",
    )
    max_backoff_ms: int = Field(
        default=30000,
        ge=0,
        description="Maximum backoff delay cap (ms)",
    )
    strategy: str = Field(
        default="republish",
        pattern=r"^(republish|log_only)$",
        description="DLQ strategy: 'republish' to a DLQ topic, or 'log_only'",
    )
    topic_prefix: str = Field(
        default="dlq",
        min_length=1,
        description="Topic prefix for DLQ topics (e.g. 'dlq' → 'dlq.original-topic')",
    )


class KafkaSettings(BaseModel):
    """Kafka connection, consumer, and transport security configuration."""

    dsn: KafkaDsn = Field(
        default=_default_kafka_dsn,
        description="Kafka connection string (kafka://host:port)",
    )
    consumer_group: str = Field(default="default-group")
    security: KafkaSecuritySettings = Field(default_factory=KafkaSecuritySettings)
    consumer: KafkaConsumerSettings = Field(
        default_factory=KafkaConsumerSettings,
        description="Consumer-specific configuration",
    )
    resilience: ResilienceSettings = Field(
        default_factory=ResilienceSettings,
        description="Message retry and dead-letter queue configuration",
    )

    @property
    def bootstrap_servers(self) -> str:
        """Extract bootstrap servers from DSN."""
        return f"{self.dsn.host}:{self.dsn.port or 9092}"


class KafkaMixin(SettingsMixin):
    """Mixin that declares kafka as required. Combine with NohikiBaseSettings.

    Provides SSL enforcement via model validator: the mixin has access to
    ``self.environment`` from NohikiBaseSettings, avoiding the need for the
    sub-model to read bare env vars.

    Usage::

        class Settings(KafkaMixin, NohikiBaseSettings):
            model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")
    """

    kafka: KafkaSettings

    @model_validator(mode="after")
    def _validate_kafka_security(self) -> Self:
        """Enforce TLS in non-development environments."""
        if self.environment not in DEVELOPMENT_ENVIRONMENTS and self.kafka.security.protocol not in {
            SecurityProtocol.SSL,
            SecurityProtocol.SASL_SSL,
        }:
            msg = "Kafka must use a TLS security protocol outside development"
            raise ValueError(msg)
        return self

    @property
    def kafka_consumer_group(self) -> str:
        """Get Kafka consumer group."""
        return self.kafka.consumer_group

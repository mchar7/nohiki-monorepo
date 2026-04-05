"""Configuration system for nohiki-kafka-client using aiokafka."""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from enum import StrEnum

from aiokafka.abc import AbstractTokenProvider
from aiokafka.coordinator.assignors.abstract import AbstractPartitionAssignor
from aiokafka.coordinator.assignors.sticky.sticky_assignor import StickyPartitionAssignor

from nohiki_kafka_client.exceptions import ConfigurationError
from nohiki_kafka_client.handlers import CircuitBreakerConfig, DLQStrategy


class SecurityProtocol(StrEnum):
    """Kafka security protocols."""

    PLAINTEXT = "PLAINTEXT"
    SSL = "SSL"
    SASL_PLAINTEXT = "SASL_PLAINTEXT"
    SASL_SSL = "SASL_SSL"


_SASL_PROTOCOLS: frozenset[SecurityProtocol] = frozenset({SecurityProtocol.SASL_PLAINTEXT, SecurityProtocol.SASL_SSL})


class SaslMechanism(StrEnum):
    """SASL authentication mechanisms."""

    PLAIN = "PLAIN"
    SCRAM_SHA_256 = "SCRAM-SHA-256"
    SCRAM_SHA_512 = "SCRAM-SHA-512"
    GSSAPI = "GSSAPI"
    OAUTHBEARER = "OAUTHBEARER"


@dataclass(slots=True)
class AutoClientConfig:
    """Configuration for auto-managing client behavior."""

    # Consumer auto-start control
    auto_start_consumers: bool = False

    # Test mode detection
    test_env_var: str = "TESTING"
    test_env_value: str = "true"
    pytest_module: str = "pytest"
    unittest_module: str = "unittest"

    # Mock response values for test mode
    mock_partition: int = 0
    mock_offset: int = 0
    mock_timestamp: int = 0
    mock_message_size_bytes: int = 100
    mock_serialization_time_ms: float = 1.0
    mock_publish_time_ms: float = 1.0
    mock_key_default: str = ""

    # Task naming
    consumer_task_prefix: str = "kafka-consumer"


@dataclass(slots=True)
class SecurityConfig:
    """Security configuration for Kafka connections."""

    protocol: SecurityProtocol = SecurityProtocol.PLAINTEXT
    sasl_mechanism: SaslMechanism | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None
    sasl_oauth_token_provider: AbstractTokenProvider | None = None
    ssl_ca_location: str | None = None
    ssl_certificate_location: str | None = None
    ssl_key_location: str | None = None
    ssl_key_password: str | None = None


@dataclass(slots=True)
class ProducerConfig:
    """Producer-specific configuration."""

    batch_size: int = 16384
    linger_ms: int = 100
    compression_type: str = "zstd"
    enable_idempotence: bool = True
    acks: str = "all"
    retry_backoff_ms: int = 100
    request_timeout_ms: int = 30000
    metadata_max_age_ms: int = 300000
    connections_max_idle_ms: int = 540000
    enable_transactions: bool = False
    transactional_id: str | None = None
    circuit_breaker: CircuitBreakerConfig | None = None


@dataclass(slots=True)
class ConsumerConfig:
    """Consumer configuration for aiokafka."""

    group_id: str = "default"
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False
    fetch_min_bytes: int = 1
    fetch_max_wait_ms: int = 500
    max_partition_fetch_bytes: int = 1048576
    max_concurrent_handlers: int = 10
    partition_assignment_strategy: tuple[type[AbstractPartitionAssignor], ...] = (StickyPartitionAssignor,)
    session_timeout_ms: int = 30000
    heartbeat_interval_ms: int = 3000
    max_poll_records: int = 500
    max_poll_interval_ms: int = 300000
    isolation_level: str = "read_committed"
    metadata_max_age_ms: int = 300000
    connections_max_idle_ms: int = 540000
    rebalance_timeout_ms: int | None = None
    group_instance_id: str | None = None
    exclude_internal_topics: bool = True
    periodic_commit_interval_seconds: float = 5.0


@dataclass(slots=True)
class GlobalDLQConfig:
    """Global Dead Letter Queue configuration for the Kafka client.

    This is the client-wide DLQ config (topic prefix, retry backoff, etc.),
    distinct from ``handlers.DLQConfig`` which is per-handler config.
    Retry state is tracked entirely in Kafka message headers: no Redis
    or in-memory state required.
    """

    strategy: DLQStrategy = DLQStrategy.REPUBLISH
    max_retries: int = 3
    retry_backoff_ms: int = 1000
    max_backoff_ms: int = 30000
    topic_prefix: str = "dlq"
    enable_logging: bool = True
    republish_timeout_ms: int = 30000


@dataclass(slots=True)
class ObservabilityConfig:
    """Observability and monitoring configuration."""

    enable_metrics: bool = True
    metrics_namespace: str = "nohiki_kafka"
    enable_tracing: bool = True
    service_name: str = "kafka-client"
    enable_structured_logging: bool = True
    log_level: str = "INFO"
    log_message_payloads: bool = False
    enable_health_checks: bool = True
    health_check_port: int = 8080


@dataclass(slots=True)
class KafkaClientConfig:
    """Main configuration for Kafka client."""

    bootstrap_servers: str
    security: SecurityConfig = field(default_factory=SecurityConfig)
    producer: ProducerConfig = field(default_factory=ProducerConfig)
    consumer: ConsumerConfig = field(default_factory=ConsumerConfig)
    dlq: GlobalDLQConfig = field(default_factory=GlobalDLQConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    auto_client: AutoClientConfig = field(default_factory=AutoClientConfig)
    client_id: str | None = None
    default_group_id: str = "nohiki-service"

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not self.bootstrap_servers:
            msg = "bootstrap_servers is required"
            raise ConfigurationError(msg)

        if self.security.protocol not in _SASL_PROTOCOLS and self.security.sasl_mechanism is SaslMechanism.OAUTHBEARER:
            msg = "OAUTHBEARER requires a SASL security protocol"
            raise ConfigurationError(msg)

        if self.security.protocol in _SASL_PROTOCOLS:
            if self.security.sasl_mechanism is SaslMechanism.OAUTHBEARER:
                if not isinstance(self.security.sasl_oauth_token_provider, AbstractTokenProvider):
                    msg = "OAUTHBEARER requires an aiokafka AbstractTokenProvider"
                    raise ConfigurationError(msg)
            elif not self.security.sasl_username or not self.security.sasl_password:
                msg = "SASL authentication requires username and password"
                raise ConfigurationError(msg)


def get_aiokafka_producer_config(config: KafkaClientConfig) -> dict[str, object]:
    """Build aiokafka producer configuration.

    Returns kwargs dict for AIOKafkaProducer constructor.
    """
    kafka_config: dict[str, object] = {
        "bootstrap_servers": config.bootstrap_servers,
        "client_id": config.client_id or f"{config.observability.service_name}-producer",
        "acks": _parse_acks(config.producer.acks),
        "compression_type": config.producer.compression_type if config.producer.compression_type != "none" else None,
        "max_batch_size": config.producer.batch_size,
        "linger_ms": config.producer.linger_ms,
        "max_request_size": 1048576,
        "request_timeout_ms": config.producer.request_timeout_ms,
        "retry_backoff_ms": config.producer.retry_backoff_ms,
        "metadata_max_age_ms": config.producer.metadata_max_age_ms,
        "connections_max_idle_ms": config.producer.connections_max_idle_ms,
        "enable_idempotence": config.producer.enable_idempotence,
    }

    if config.producer.enable_transactions and config.producer.transactional_id:
        kafka_config["transactional_id"] = config.producer.transactional_id

    _add_aiokafka_security_config(kafka_config, config.security)

    return kafka_config


def get_aiokafka_consumer_config(config: KafkaClientConfig, group_id: str | None = None) -> dict[str, object]:
    """Build aiokafka consumer configuration.

    Returns kwargs dict for AIOKafkaConsumer constructor.
    Includes robustness settings for containerized environments.
    """
    kafka_config: dict[str, object] = {
        "bootstrap_servers": config.bootstrap_servers,
        "client_id": config.client_id or f"{config.observability.service_name}-consumer",
        "group_id": group_id or config.consumer.group_id,
        "auto_offset_reset": config.consumer.auto_offset_reset,
        "enable_auto_commit": config.consumer.enable_auto_commit,
        "fetch_min_bytes": config.consumer.fetch_min_bytes,
        "fetch_max_wait_ms": config.consumer.fetch_max_wait_ms,
        "max_partition_fetch_bytes": config.consumer.max_partition_fetch_bytes,
        "session_timeout_ms": config.consumer.session_timeout_ms,
        "heartbeat_interval_ms": config.consumer.heartbeat_interval_ms,
        "max_poll_records": config.consumer.max_poll_records,
        "max_poll_interval_ms": config.consumer.max_poll_interval_ms,
        "partition_assignment_strategy": config.consumer.partition_assignment_strategy,
        "isolation_level": config.consumer.isolation_level,
        "metadata_max_age_ms": config.consumer.metadata_max_age_ms,
        "connections_max_idle_ms": config.consumer.connections_max_idle_ms,
        "exclude_internal_topics": config.consumer.exclude_internal_topics,
    }

    if config.consumer.rebalance_timeout_ms is not None:
        kafka_config["rebalance_timeout_ms"] = config.consumer.rebalance_timeout_ms

    if config.consumer.group_instance_id is not None:
        kafka_config["group_instance_id"] = config.consumer.group_instance_id

    _add_aiokafka_security_config(kafka_config, config.security)

    return kafka_config


def _parse_acks(acks: str) -> int | str:
    """Parse acks config value to aiokafka format."""
    if acks == "all":
        return "all"
    try:
        return int(acks)
    except ValueError:
        return "all"


def _add_aiokafka_security_config(kafka_config: dict[str, object], security: SecurityConfig) -> None:
    """Add security configuration for aiokafka."""
    kafka_config["security_protocol"] = security.protocol.value

    if security.protocol in (SecurityProtocol.SASL_PLAINTEXT, SecurityProtocol.SASL_SSL):
        mechanism = security.sasl_mechanism or SaslMechanism.PLAIN
        kafka_config["sasl_mechanism"] = mechanism.value
        if mechanism is SaslMechanism.OAUTHBEARER:
            if not isinstance(security.sasl_oauth_token_provider, AbstractTokenProvider):
                msg = "OAUTHBEARER requires an aiokafka AbstractTokenProvider"
                raise ConfigurationError(msg)
            kafka_config["sasl_oauth_token_provider"] = security.sasl_oauth_token_provider
        else:
            kafka_config["sasl_plain_username"] = security.sasl_username
            kafka_config["sasl_plain_password"] = security.sasl_password

    if security.protocol in (SecurityProtocol.SSL, SecurityProtocol.SASL_SSL):
        ssl_context = create_ssl_context(security)
        if ssl_context:
            kafka_config["ssl_context"] = ssl_context


def create_ssl_context(security: SecurityConfig) -> ssl.SSLContext | None:
    """Create SSL context from security configuration."""
    if not any([security.ssl_ca_location, security.ssl_certificate_location, security.ssl_key_location]):
        return None

    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3

    if security.ssl_ca_location:
        ssl_context.load_verify_locations(cafile=security.ssl_ca_location)

    if security.ssl_certificate_location and security.ssl_key_location:
        ssl_context.load_cert_chain(
            certfile=security.ssl_certificate_location,
            keyfile=security.ssl_key_location,
            password=security.ssl_key_password,
        )

    return ssl_context

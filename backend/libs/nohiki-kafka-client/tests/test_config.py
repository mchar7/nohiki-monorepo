"""Unit tests for Kafka client configuration with aiokafka."""

from __future__ import annotations

import pytest
from nohiki_kafka_client.config import (
    ConsumerConfig,
    GlobalDLQConfig,
    KafkaClientConfig,
    ObservabilityConfig,
    ProducerConfig,
    SaslMechanism,
    SecurityConfig,
    SecurityProtocol,
    get_aiokafka_consumer_config,
    get_aiokafka_producer_config,
)
from nohiki_kafka_client.exceptions import ConfigurationError


class TestKafkaClientConfigValidation:
    """Tests for KafkaClientConfig validation."""

    def test_valid_config_creates_successfully(self) -> None:
        """Valid configuration creates successfully."""
        config = KafkaClientConfig(bootstrap_servers="localhost:29092")
        assert config.bootstrap_servers == "localhost:29092"

    def test_missing_bootstrap_servers_raises(self) -> None:
        """Missing bootstrap_servers raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="bootstrap_servers is required"):
            KafkaClientConfig(bootstrap_servers="")

    def test_sasl_without_credentials_raises(self) -> None:
        """SASL protocol without credentials raises ConfigurationError."""
        security = SecurityConfig(
            protocol=SecurityProtocol.SASL_PLAINTEXT,
            sasl_username=None,
            sasl_password=None,
        )
        with pytest.raises(ConfigurationError, match="SASL authentication requires"):
            KafkaClientConfig(bootstrap_servers="localhost:29092", security=security)

    def test_sasl_ssl_without_credentials_raises(self) -> None:
        """SASL_SSL protocol without credentials raises ConfigurationError."""
        security = SecurityConfig(
            protocol=SecurityProtocol.SASL_SSL,
            sasl_username="",
            sasl_password="secret",
        )
        with pytest.raises(ConfigurationError, match="SASL authentication requires"):
            KafkaClientConfig(bootstrap_servers="localhost:29092", security=security)

    def test_sasl_with_credentials_succeeds(self) -> None:
        """SASL protocol with credentials succeeds."""
        security = SecurityConfig(
            protocol=SecurityProtocol.SASL_PLAINTEXT,
            sasl_username="user",
            sasl_password="password",
        )
        config = KafkaClientConfig(bootstrap_servers="localhost:29092", security=security)
        assert config.security.sasl_username == "user"


class TestGetAiokafkaProducerConfig:
    """Tests for get_aiokafka_producer_config function."""

    def test_basic_producer_config(self) -> None:
        """Basic producer config is built correctly."""
        config = KafkaClientConfig(
            bootstrap_servers="localhost:29092",
            client_id="test-producer",
        )
        kafka_config = get_aiokafka_producer_config(config)

        assert kafka_config["bootstrap_servers"] == "localhost:29092"
        assert kafka_config["client_id"] == "test-producer"
        assert "max_batch_size" in kafka_config
        assert "linger_ms" in kafka_config

    def test_producer_config_uses_service_name_as_client_id(self) -> None:
        """Producer config uses service name if no client_id."""
        observability = ObservabilityConfig(service_name="my-service")
        config = KafkaClientConfig(
            bootstrap_servers="localhost:29092",
            observability=observability,
        )
        kafka_config = get_aiokafka_producer_config(config)

        assert kafka_config["client_id"] == "my-service-producer"


class TestGetAiokafkaConsumerConfig:
    """Tests for get_aiokafka_consumer_config function."""

    def test_basic_consumer_config(self) -> None:
        """Basic consumer config is built correctly."""
        config = KafkaClientConfig(
            bootstrap_servers="localhost:29092",
            client_id="test-consumer",
        )
        kafka_config = get_aiokafka_consumer_config(config, group_id="test-group")

        assert kafka_config["bootstrap_servers"] == "localhost:29092"
        assert kafka_config["client_id"] == "test-consumer"
        assert kafka_config["group_id"] == "test-group"

    def test_consumer_config_uses_default_group_id(self) -> None:
        """Consumer config uses consumer.group_id if no group_id provided."""
        consumer = ConsumerConfig(group_id="default-group")
        config = KafkaClientConfig(
            bootstrap_servers="localhost:29092",
            consumer=consumer,
        )
        kafka_config = get_aiokafka_consumer_config(config)

        assert kafka_config["group_id"] == "default-group"

    def test_consumer_config_with_partition_assignment_strategy(self) -> None:
        """Consumer config passes aiokafka assignor classes directly."""
        from aiokafka.coordinator.assignors.range import RangePartitionAssignor

        consumer = ConsumerConfig(
            group_id="test-group",
            partition_assignment_strategy=(RangePartitionAssignor,),
        )
        config = KafkaClientConfig(
            bootstrap_servers="localhost:29092",
            consumer=consumer,
        )
        kafka_config = get_aiokafka_consumer_config(config)
        assert kafka_config["partition_assignment_strategy"] == (RangePartitionAssignor,)

    def test_consumer_config_default_uses_sticky_assignor(self) -> None:
        """Default partition assignment strategy is StickyPartitionAssignor."""
        from aiokafka.coordinator.assignors.sticky.sticky_assignor import StickyPartitionAssignor

        config = KafkaClientConfig(bootstrap_servers="localhost:29092")
        kafka_config = get_aiokafka_consumer_config(config)
        assert kafka_config["partition_assignment_strategy"] == (StickyPartitionAssignor,)


class TestSecurityConfig:
    """Tests for security configuration."""

    def test_plaintext_security(self) -> None:
        """Plaintext security adds minimal config."""
        security = SecurityConfig(protocol=SecurityProtocol.PLAINTEXT)
        config = KafkaClientConfig(bootstrap_servers="localhost:29092", security=security)
        kafka_config = get_aiokafka_producer_config(config)

        assert kafka_config["security_protocol"] == "PLAINTEXT"

    def test_sasl_plaintext_security(self) -> None:
        """SASL_PLAINTEXT adds authentication config."""
        security = SecurityConfig(
            protocol=SecurityProtocol.SASL_PLAINTEXT,
            sasl_mechanism=SaslMechanism.PLAIN,
            sasl_username="user",
            sasl_password="pass",
        )
        config = KafkaClientConfig(bootstrap_servers="localhost:29092", security=security)
        kafka_config = get_aiokafka_producer_config(config)

        assert kafka_config["security_protocol"] == "SASL_PLAINTEXT"
        assert kafka_config["sasl_mechanism"] == "PLAIN"
        assert kafka_config["sasl_plain_username"] == "user"
        assert kafka_config["sasl_plain_password"] == "pass"

    def test_sasl_ssl_security(self) -> None:
        """SASL_SSL adds both auth and ssl context."""
        security = SecurityConfig(
            protocol=SecurityProtocol.SASL_SSL,
            sasl_mechanism=SaslMechanism.SCRAM_SHA_512,
            sasl_username="user",
            sasl_password="pass",
        )
        config = KafkaClientConfig(bootstrap_servers="localhost:29092", security=security)
        kafka_config = get_aiokafka_producer_config(config)

        assert kafka_config["security_protocol"] == "SASL_SSL"
        assert kafka_config["sasl_mechanism"] == "SCRAM-SHA-512"


class TestConsumerConfigDefaults:
    """Tests for ConsumerConfig default values."""

    def test_default_values(self) -> None:
        """ConsumerConfig has sensible defaults."""
        consumer = ConsumerConfig()
        assert consumer.group_id == "default"
        assert consumer.max_concurrent_handlers == 10
        assert consumer.isolation_level == "read_committed"
        assert consumer.max_poll_interval_ms == 300000
        assert consumer.metadata_max_age_ms == 300000
        assert consumer.connections_max_idle_ms == 540000
        assert consumer.exclude_internal_topics is True
        assert consumer.rebalance_timeout_ms is None
        assert consumer.group_instance_id is None


class TestProducerConfigDefaults:
    """Tests for ProducerConfig default values."""

    def test_default_values(self) -> None:
        """ProducerConfig has sensible defaults."""
        producer = ProducerConfig()
        assert producer.batch_size == 16384
        assert producer.linger_ms >= 0
        assert producer.compression_type == "zstd"
        assert producer.enable_idempotence is True
        assert producer.acks == "all"
        assert producer.metadata_max_age_ms == 300000
        assert producer.connections_max_idle_ms == 540000


class TestGlobalDLQConfigDefaults:
    """Tests for GlobalDLQConfig default values."""

    def test_default_values(self) -> None:
        """GlobalDLQConfig has sensible defaults."""
        dlq = GlobalDLQConfig()
        assert dlq.max_retries >= 0
        assert dlq.retry_backoff_ms > 0
        assert dlq.max_backoff_ms >= dlq.retry_backoff_ms

"""Unit tests for Kafka client factory functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from nohiki_kafka_client.client.factory import (
    HasKafkaSettings,
    create_kafka_client,
    get_kafka_client,
)
from pydantic import SecretStr


class TestGetKafkaClient:
    """Tests for get_kafka_client function."""

    def test_returns_client_instance(self) -> None:
        """get_kafka_client returns the global AutoKafkaClient instance."""
        from nohiki_kafka_client.client.auto_client import _global_instance

        mock_client = MagicMock()
        original = _global_instance[0]
        try:
            _global_instance[0] = mock_client
            result = get_kafka_client()
            assert result is mock_client
        finally:
            _global_instance[0] = original

    def test_raises_when_not_initialized(self) -> None:
        """get_kafka_client raises RuntimeError when no instance exists."""
        from nohiki_kafka_client.client.auto_client import _global_instance

        original = _global_instance[0]
        try:
            _global_instance[0] = None
            with pytest.raises(RuntimeError, match="not initialized"):
                get_kafka_client()
        finally:
            _global_instance[0] = original


class TestHasKafkaSettings:
    """Tests for HasKafkaSettings protocol."""

    def test_protocol_check(self) -> None:
        """HasKafkaSettings is a runtime checkable protocol."""
        mock_settings = MagicMock()
        mock_settings.service_name = "test-service"
        mock_settings.kafka = MagicMock()
        mock_settings.observability = MagicMock()
        assert isinstance(mock_settings, HasKafkaSettings)


class TestCreateKafkaClient:
    """Tests for create_kafka_client function."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings object."""
        settings = MagicMock()
        settings.service_name = "test-service"
        settings.kafka.bootstrap_servers = "localhost:29092"
        settings.kafka.consumer_group = "test-group"
        settings.kafka.security.protocol = "SASL_SSL"
        settings.kafka.security.sasl.mechanism = "PLAIN"
        settings.kafka.security.sasl.username = "$ConnectionString"
        settings.kafka.security.sasl.password = SecretStr("event-hubs-secret")
        settings.kafka.security.tls.ca_location = "/tls/ca.pem"
        settings.kafka.security.tls.certificate_location = "/tls/client.pem"
        settings.kafka.security.tls.key_location = "/tls/client-key.pem"
        settings.kafka.security.tls.key_password = SecretStr("key-secret")
        settings.kafka.resilience.strategy = "republish"
        settings.kafka.resilience.max_retries = 3
        settings.kafka.resilience.retry_backoff_ms = 500
        settings.kafka.resilience.max_backoff_ms = 60000
        settings.kafka.resilience.topic_prefix = "dlq"
        settings.observability.logging.level = "INFO"
        return settings

    def test_creates_client(self, mock_settings: MagicMock) -> None:
        """create_kafka_client creates and returns a configured client."""
        with patch("nohiki_kafka_client.client.factory.AutoKafkaClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            result = create_kafka_client(mock_settings)

            mock_client_class.assert_called_once()
            assert result == mock_client

    def test_config_has_correct_values(self, mock_settings: MagicMock) -> None:
        """create_kafka_client creates config with correct values."""
        with patch("nohiki_kafka_client.client.factory.AutoKafkaClient") as mock_client_class:
            create_kafka_client(mock_settings)

            call_args = mock_client_class.call_args
            config = call_args[0][0]
            assert config.bootstrap_servers == "localhost:29092"
            assert config.consumer.group_id == "test-group"
            assert config.observability.service_name == "test-service"
            assert config.observability.log_level == "INFO"
            assert config.security.protocol == "SASL_SSL"
            assert config.security.sasl_mechanism == "PLAIN"
            assert config.security.sasl_username == "$ConnectionString"
            assert config.security.sasl_password == "event-hubs-secret"
            assert config.security.ssl_ca_location == "/tls/ca.pem"
            assert config.security.ssl_certificate_location == "/tls/client.pem"
            assert config.security.ssl_key_location == "/tls/client-key.pem"
            assert config.security.ssl_key_password == "key-secret"

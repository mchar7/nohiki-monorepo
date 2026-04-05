"""Tests for KafkaSettings."""

from __future__ import annotations

import pytest
from nohiki_core_settings import NohikiBaseSettings
from nohiki_kafka_client import KafkaMixin, KafkaSettings
from pydantic import Field, ValidationError
from pydantic_settings import SettingsConfigDict


class _TestKafkaSettings(KafkaMixin, NohikiBaseSettings):
    """Test settings combining KafkaMixin with NohikiBaseSettings."""

    # secrets_dir=None keeps these tests hermetic: the host /run/secrets must not leak in
    model_config = SettingsConfigDict(env_prefix="TEST_KAFKA_", secrets_dir=None)

    service_name: str = "test-kafka-service"
    service_name_friendly: str = "Test Kafka Service"
    service_desc_friendly: str = "Test service for Kafka settings"
    service_version: str = "0.0.1-test"
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)


class TestKafkaSettingsDefaults:
    """Tests for default settings."""

    def test_default_dsn(self) -> None:
        """Test default Kafka DSN."""
        settings = KafkaSettings()
        assert settings.bootstrap_servers == "localhost:29092"
        assert settings.consumer_group == "default-group"
        assert settings.security.protocol.value == "PLAINTEXT"

    def test_default_consumer_group(self) -> None:
        """Test default consumer group."""
        settings = KafkaSettings()
        assert settings.consumer_group == "default-group"


class TestKafkaSettingsCustomDsn:
    """Tests for custom DSN configuration."""

    def test_custom_dsn_plaintext(self) -> None:
        """Test custom plaintext Kafka DSN."""
        settings = KafkaSettings.model_validate({"dsn": "kafka://broker1:9092"})
        assert settings.bootstrap_servers == "broker1:9092"

    def test_custom_dsn_different_port(self) -> None:
        """Test custom Kafka DSN with different port."""
        settings = KafkaSettings.model_validate({"dsn": "kafka://broker:9094"})
        assert settings.bootstrap_servers == "broker:9094"

    def test_custom_dsn_with_default_port(self) -> None:
        """Test DSN without explicit port uses default."""
        settings = KafkaSettings.model_validate({"dsn": "kafka://broker1"})
        assert settings.bootstrap_servers == "broker1:9092"


class TestKafkaSettingsConsumerGroup:
    """Tests for consumer group configuration."""

    def test_custom_consumer_group(self) -> None:
        """Test custom consumer group."""
        settings = KafkaSettings.model_validate({"dsn": "kafka://broker:9092", "consumer_group": "my-service-group"})
        assert settings.consumer_group == "my-service-group"

    def test_consumer_group_with_custom_dsn(self) -> None:
        """Test consumer group with custom DSN."""
        settings = KafkaSettings.model_validate({"dsn": "kafka://broker:9093", "consumer_group": "secure-group"})
        assert settings.consumer_group == "secure-group"


class TestKafkaSettingsValidation:
    """Tests for validation logic."""

    def test_invalid_dsn_scheme(self) -> None:
        """Test that invalid DSN scheme raises error."""
        with pytest.raises(ValidationError):
            KafkaSettings.model_validate({"dsn": "http://broker:9092"})

    def test_sasl_ssl_requires_complete_credentials(self) -> None:
        """SASL protocols fail closed when any credential is missing."""
        for sasl in (
            {"mechanism": "PLAIN", "username": "$ConnectionString"},
            {"mechanism": "PLAIN", "password": "secret"},
            {"username": "$ConnectionString", "password": "secret"},
        ):
            with pytest.raises(ValidationError, match="mechanism, username, and password"):
                KafkaSettings.model_validate(
                    {"security": {"protocol": "SASL_SSL", "sasl": sasl}},
                )

    def test_sasl_ssl_plain_and_tls_paths_are_preserved(self) -> None:
        """Event Hubs auth and optional client TLS paths map into settings."""
        settings = KafkaSettings.model_validate(
            {
                "dsn": "kafka://event-hubs.example:9093",
                "security": {
                    "protocol": "SASL_SSL",
                    "sasl": {
                        "mechanism": "PLAIN",
                        "username": "$ConnectionString",
                        "password": "event-hubs-connection-string",
                    },
                    "tls": {
                        "ca_location": "/tls/ca.pem",
                        "certificate_location": "/tls/client.pem",
                        "key_location": "/tls/client-key.pem",
                        "key_password": "key-secret",
                    },
                },
            },
        )

        assert settings.security.protocol.value == "SASL_SSL"
        assert settings.security.sasl.mechanism is not None
        assert settings.security.sasl.mechanism.value == "PLAIN"
        assert settings.security.sasl.password is not None
        assert settings.security.sasl.password.get_secret_value() == "event-hubs-connection-string"
        assert settings.security.tls.ca_location == "/tls/ca.pem"
        assert settings.security.tls.certificate_location == "/tls/client.pem"
        assert settings.security.tls.key_location == "/tls/client-key.pem"
        assert settings.security.tls.key_password is not None
        assert settings.security.tls.key_password.get_secret_value() == "key-secret"


class TestKafkaSettingsBootstrapServersProperty:
    """Tests for bootstrap_servers property."""

    def test_extracts_host_and_port(self) -> None:
        """Test bootstrap_servers extracts host and port from DSN."""
        settings = KafkaSettings.model_validate({"dsn": "kafka://myhost:9094"})
        assert settings.bootstrap_servers == "myhost:9094"

    def test_uses_default_port(self) -> None:
        """Test bootstrap_servers uses default port when not specified."""
        settings = KafkaSettings.model_validate({"dsn": "kafka://myhost"})
        assert settings.bootstrap_servers == "myhost:9092"

    def test_security_protocol_defaults_to_plaintext(self) -> None:
        """Local Kafka remains plaintext-compatible by default."""
        settings = KafkaSettings.model_validate({"dsn": "kafka://broker:9093"})
        assert settings.bootstrap_servers == "broker:9093"
        assert settings.security.protocol.value == "PLAINTEXT"


class TestKafkaMixinProductionValidation:
    """Tests for production environment validation via KafkaMixin."""

    def test_plaintext_in_production_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production rejects Kafka protocols without TLS."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(ValidationError, match="TLS security protocol outside development"):
            _TestKafkaSettings(kafka=KafkaSettings())

    def test_sasl_ssl_in_production_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production accepts complete Event Hubs SASL_SSL settings."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        settings = _TestKafkaSettings(
            kafka=KafkaSettings.model_validate(
                {
                    "security": {
                        "protocol": "SASL_SSL",
                        "sasl": {
                            "mechanism": "PLAIN",
                            "username": "$ConnectionString",
                            "password": "secret",
                        },
                    },
                },
            ),
        )
        assert settings.kafka.security.protocol.value == "SASL_SSL"

    def test_development_allows_plaintext(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Local development retains plaintext Kafka compatibility."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        settings = _TestKafkaSettings(kafka=KafkaSettings())
        assert settings.kafka.security.protocol.value == "PLAINTEXT"

    def test_kafka_consumer_group_property(self) -> None:
        """Test kafka_consumer_group convenience property on mixin."""
        settings = _TestKafkaSettings(
            kafka=KafkaSettings.model_validate({"consumer_group": "my-group"}),
        )
        assert settings.kafka_consumer_group == "my-group"

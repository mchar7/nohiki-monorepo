"""Tests for NohikiBaseSettings."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from nohiki_core_settings import (
    LoggingSettings,
    NohikiBaseSettings,
    ObservabilitySettings,
)
from nohiki_core_settings.base import AzureKeyVaultNotInstalledError
from nohiki_db_utils import DatabaseMixin, DatabaseSettings
from nohiki_kafka_client import KafkaMixin, KafkaSettings
from nohiki_kafka_client.config.settings import _default_kafka_dsn
from nohiki_redis_utils import RedisMixin
from nohiki_redis_utils.settings import _default_redis_dsn
from nohiki_s3_client import S3Mixin, S3Settings
from pydantic import Field, ValidationError
from pydantic_settings import SettingsConfigDict


class _BaseTestSettings(NohikiBaseSettings):
    """Base test settings with required fields populated."""

    service_name: str = "test-service"
    service_name_friendly: str = "Test Service"
    service_desc_friendly: str = "Test service for unit tests"
    service_version: str = "0.0.1-test"


class _TestSettingsWithDatabase(DatabaseMixin, _BaseTestSettings):
    """Test settings with database mixin."""

    database: DatabaseSettings = Field(
        default_factory=lambda: DatabaseSettings(dsn="postgresql://localhost/test", schema_name="test_schema")
    )


class _TestSettingsWithKafka(KafkaMixin, _BaseTestSettings):
    """Test settings with kafka mixin."""

    kafka: KafkaSettings = Field(default_factory=lambda: KafkaSettings(dsn=_default_kafka_dsn))


class _TestSettingsWithRedis(RedisMixin, _BaseTestSettings):
    """Test settings with redis mixin."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        protected_namespaces=(),  # Disable pydantic field shadowing warnings
    )


class _TestSettingsWithS3(S3Mixin, _BaseTestSettings):
    """Test settings with S3 mixin."""

    s3: S3Settings = Field(default_factory=lambda: S3Settings(bucket="test-bucket"))


class TestNohikiBaseSettingsDefaults:
    """Tests for default settings values."""

    def test_service_identity_defaults(self) -> None:
        """Test default service identity values."""
        settings = _BaseTestSettings()
        assert settings.service_name == "test-service"
        assert settings.service_name_friendly == "Test Service"
        assert settings.service_desc_friendly == "Test service for unit tests"
        assert settings.service_version == "0.0.1-test"

    def test_runtime_defaults(self) -> None:
        """Test default runtime values."""
        settings = _BaseTestSettings()
        assert settings.debug is False
        assert settings.host == "127.0.0.1"
        assert settings.port == 8000
        assert settings.api_prefix == "/api/v1"

    def test_nested_settings_defaults(self) -> None:
        """Test default nested settings values."""
        settings = _BaseTestSettings()
        assert isinstance(settings.observability, ObservabilitySettings)


class TestNohikiBaseSettingsCustom:
    """Tests for custom configuration."""

    def test_service_identity_custom(self) -> None:
        """Test custom service identity values."""
        settings = _BaseTestSettings(
            service_name="my-service",
            service_name_friendly="My Service",
            service_desc_friendly="A test service",
            service_version="1.2.3",
        )
        assert settings.service_name == "my-service"
        assert settings.service_name_friendly == "My Service"
        assert settings.service_desc_friendly == "A test service"
        assert settings.service_version == "1.2.3"

    def test_runtime_custom(self) -> None:
        """Test custom runtime values."""
        settings = _BaseTestSettings(
            debug=True,
            host="127.0.0.1",
            port=9000,
            api_prefix="/api/v2",
        )
        assert settings.debug is True
        assert settings.host == "127.0.0.1"
        assert settings.port == 9000
        assert settings.api_prefix == "/api/v2"

    def test_nested_database_settings(self) -> None:
        """Test nested database settings."""
        settings = _TestSettingsWithDatabase.model_validate(
            {
                "database": {
                    "dsn": "postgresql://localhost/test",
                    "schema_name": "test_schema",
                },
            }
        )
        assert settings.database is not None
        assert "localhost" in settings.database.connection_string

    def test_nested_redis_settings(self) -> None:
        """Test nested redis settings."""
        settings = _TestSettingsWithRedis.model_validate(
            {
                "redis": {
                    "dsn": "redis://redis.example.com:6380/0",
                },
            }
        )
        assert settings.redis is not None
        assert "redis.example.com:6380" in settings.redis.connection_string

    def test_nested_kafka_settings(self) -> None:
        """Test nested kafka settings."""
        settings = _TestSettingsWithKafka.model_validate(
            {
                "kafka": {
                    "dsn": "kafka://kafka1:9092",
                    "consumer_group": "my-group",
                },
            }
        )
        assert settings.kafka is not None
        assert "kafka1:9092" in settings.kafka.bootstrap_servers
        assert settings.kafka.consumer_group == "my-group"

    def test_nested_observability_settings(self) -> None:
        """Test nested observability settings."""
        settings = _BaseTestSettings(
            observability=ObservabilitySettings(
                otel_endpoint="http://otel:4317",
                logging=LoggingSettings(level="DEBUG"),
            ),
        )
        assert settings.observability.otel_endpoint == "http://otel:4317"
        assert settings.observability.logging.level == "DEBUG"


class TestNohikiBaseSettingsValidation:
    """Tests for validation logic."""

    def test_port_bounds(self) -> None:
        """Test port validation bounds."""
        settings = _BaseTestSettings(port=1)
        assert settings.port == 1

        settings = _BaseTestSettings(port=65535)
        assert settings.port == 65535

        with pytest.raises(ValidationError):
            _BaseTestSettings(port=0)

        with pytest.raises(ValidationError):
            _BaseTestSettings(port=65536)


class TestNohikiBaseSettingsEnvironment:
    """Tests for environment variable handling."""

    def test_env_variable_service_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test service_name from environment variable."""
        monkeypatch.setenv("SERVICE_NAME", "env-service")
        settings = _BaseTestSettings()
        assert settings.service_name == "env-service"

    def test_env_variable_debug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test debug from environment variable."""
        monkeypatch.setenv("DEBUG", "true")
        settings = _BaseTestSettings()
        assert settings.debug is True

    def test_env_variable_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test port from environment variable."""
        monkeypatch.setenv("PORT", "9000")
        settings = _BaseTestSettings()
        assert settings.port == 9000

    def test_nested_delimiter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test nested delimiter for nested settings."""
        monkeypatch.setenv("OBSERVABILITY__LOGGING__LEVEL", "DEBUG")
        monkeypatch.setenv("OBSERVABILITY__LOGGING__FORMAT", "console")
        settings = _BaseTestSettings()
        assert settings.observability.logging.level == "DEBUG"
        assert settings.observability.logging.format == "console"

    def test_extra_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that extra environment variables are ignored."""
        monkeypatch.setenv("UNKNOWN_SETTING", "value")
        settings = _BaseTestSettings()
        assert not hasattr(settings, "unknown_setting")


class TestAzureKeyVaultIntegration:
    """Tests for Azure Key Vault integration."""

    def test_no_azure_without_env_var(self) -> None:
        """Test that Azure Key Vault is not used without env var."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AZURE_KEY_VAULT_URL", None)
            settings = _BaseTestSettings()
            assert isinstance(settings, _BaseTestSettings)

    def test_settings_load_without_azure_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that settings load correctly without AZURE_KEY_VAULT_URL."""
        monkeypatch.delenv("AZURE_KEY_VAULT_URL", raising=False)

        class CustomSettings(NohikiBaseSettings):
            service_name: str = "test-service"
            service_name_friendly: str = "Test Service"
            service_desc_friendly: str = "Test"
            service_version: str = "1.0.0"

        settings = CustomSettings()
        assert settings.service_name == "test-service"


class TestSettingsInheritance:
    """Tests for settings class inheritance."""

    def test_subclass_inherits_config(self) -> None:
        """Test that subclasses inherit model_config."""

        class MyServiceSettings(NohikiBaseSettings):
            service_name: str = "my-service"
            service_name_friendly: str = "My Service"
            service_desc_friendly: str = "Test"
            service_version: str = "1.0.0"
            custom_setting: str = "default"

        settings = MyServiceSettings()
        assert settings.service_name == "my-service"
        assert settings.custom_setting == "default"

    def test_subclass_can_override_defaults(self) -> None:
        """Test that subclasses can override defaults."""

        class MyServiceSettings(NohikiBaseSettings):
            service_name: str = "my-service"
            service_name_friendly: str = "My Service"
            service_desc_friendly: str = "Test"
            service_version: str = "2.0.0"

        settings = MyServiceSettings()
        assert settings.service_name == "my-service"
        assert settings.service_version == "2.0.0"

    def test_subclass_with_required_fields(self) -> None:
        """Test subclass with required fields."""

        class MyServiceSettings(NohikiBaseSettings):
            service_name: str = "my-service"
            service_name_friendly: str = "My Service"
            service_desc_friendly: str = "Test"
            service_version: str = "1.0.0"
            api_key: str = Field(...)

        with pytest.raises(ValidationError):
            MyServiceSettings()

        settings = MyServiceSettings(api_key="secret")
        assert settings.api_key == "secret"


class TestModelConfig:
    """Tests for model configuration."""

    def test_case_sensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that settings are case sensitive."""
        monkeypatch.setenv("service_name", "lowercase")
        monkeypatch.setenv("SERVICE_NAME", "uppercase")
        settings = _BaseTestSettings()
        assert settings.service_name == "uppercase"

    def test_env_nested_delimiter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test nested delimiter configuration."""
        monkeypatch.setenv("OBSERVABILITY__OTEL_ENDPOINT", "http://test:4317")
        settings = _BaseTestSettings()
        assert settings.observability.otel_endpoint == "http://test:4317"


class TestMixinProperties:
    """Tests for mixin convenience properties."""

    def test_database_mixin_database_url_property(self) -> None:
        """Test DatabaseMixin.database_url property."""
        settings = _TestSettingsWithDatabase(
            database=DatabaseSettings(dsn="postgresql://user:pass@localhost:5432/testdb", schema_name="test_schema"),
        )
        assert "postgresql+asyncpg://" in settings.database_url
        assert "localhost:5432" in settings.database_url
        assert "testdb" in settings.database_url

    def test_redis_mixin_redis_url_property(self) -> None:
        """Test RedisMixin.redis_url property."""
        settings = _TestSettingsWithRedis()
        assert str(settings.redis_url) == str(_default_redis_dsn)

    def test_kafka_mixin_kafka_consumer_group_property(self) -> None:
        """Test KafkaMixin.kafka_consumer_group property."""
        settings = _TestSettingsWithKafka(
            kafka=KafkaSettings(dsn=_default_kafka_dsn, consumer_group="my-consumer-group"),
        )
        assert settings.kafka_consumer_group == "my-consumer-group"

    def test_s3_mixin_s3_bucket_property(self) -> None:
        """Test S3Mixin.s3_bucket property."""
        settings = _TestSettingsWithS3(
            s3=S3Settings(bucket="my-test-bucket"),
        )
        assert settings.s3_bucket == "my-test-bucket"


class TestAzureKeyVaultError:
    """Tests for Azure Key Vault error handling."""

    def test_azure_keyvault_not_installed_error_raised(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test AzureKeyVaultNotInstalledError is raised when vault URL set but azure-identity missing."""
        monkeypatch.setenv("AZURE_KEY_VAULT_URL", "https://myvault.vault.azure.net")

        # Mock the azure identity availability check to return False
        import nohiki_core_settings.base as base_module

        original_factory = base_module._azure_keyvault_source_factory
        monkeypatch.setattr(base_module, "_azure_keyvault_source_factory", None)

        try:
            with pytest.raises(AzureKeyVaultNotInstalledError):
                _BaseTestSettings()
        finally:
            monkeypatch.setattr(base_module, "_azure_keyvault_source_factory", original_factory)


@pytest.fixture
def plain_nested_secrets(tmp_path: Path) -> Path:
    """Create an ordinary nested secrets directory without credential bytes."""
    s3 = tmp_path / "s3"
    s3.mkdir()
    (s3 / "access_key").touch()
    (s3 / "secret_key").touch()
    (s3 / "bucket").write_text("fixture-bucket", encoding="utf-8")
    return tmp_path


@pytest.fixture
def kubelet_projected_secrets(tmp_path: Path) -> Path:
    """Create the kubelet atomic-writer layout, including its logical symlinks."""
    generation = tmp_path / "..2026_08_04_00_00_00.000000000"
    s3 = generation / "s3"
    s3.mkdir(parents=True)
    (s3 / "access_key").touch()
    (s3 / "secret_key").touch()
    (s3 / "bucket").write_text("fixture-bucket", encoding="utf-8")
    (tmp_path / "..data").symlink_to(generation.name, target_is_directory=True)
    (tmp_path / "s3").symlink_to("..data/s3", target_is_directory=True)
    return tmp_path


class TestFileSecretsSource:
    """Tests for how the file-secrets source resolves its directory."""

    def test_secrets_dir_is_resolved_at_construction(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A SECRETS_DIR set after import time still feeds the file-secrets source."""
        (tmp_path / "service_version").write_text("9.9.9-from-secret", encoding="utf-8")
        monkeypatch.setenv("SECRETS_DIR", str(tmp_path))

        assert _BaseTestSettings().service_version == "9.9.9-from-secret"

    def test_class_config_secrets_dir_overrides_the_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A class that pins its own ``secrets_dir`` keeps it when SECRETS_DIR names another tree."""
        (tmp_path / "service_version").write_text("9.9.9-from-environment", encoding="utf-8")
        pinned = tmp_path / "pinned"
        pinned.mkdir()
        (pinned / "service_version").write_text("1.2.3-from-class-config", encoding="utf-8")
        monkeypatch.setenv("SECRETS_DIR", str(tmp_path))

        class _PinnedSettings(_BaseTestSettings):
            model_config = SettingsConfigDict(secrets_dir=str(pinned))

        assert _PinnedSettings().service_version == "1.2.3-from-class-config"

    def test_plain_nested_directory_surfaces_logical_s3_keys(
        self,
        monkeypatch: pytest.MonkeyPatch,
        plain_nested_secrets: Path,
    ) -> None:
        """Plain directories continue to expose nested keys from the mount root."""
        monkeypatch.setenv("SECRETS_DIR", str(plain_nested_secrets))

        settings = _TestSettingsWithS3()

        assert settings.s3.access_key is not None
        assert settings.s3.secret_key is not None
        assert len(settings.s3.access_key.get_secret_value()) == 0
        assert len(settings.s3.secret_key.get_secret_value()) == 0

    def test_kubelet_projected_directory_surfaces_logical_s3_keys(
        self,
        monkeypatch: pytest.MonkeyPatch,
        kubelet_projected_secrets: Path,
    ) -> None:
        """Kubelet control links cannot hide the logical nested secret paths."""
        monkeypatch.setenv("SECRETS_DIR", str(kubelet_projected_secrets))

        settings = _TestSettingsWithS3()

        assert settings.s3.access_key is not None
        assert settings.s3.secret_key is not None
        assert len(settings.s3.access_key.get_secret_value()) == 0
        assert len(settings.s3.secret_key.get_secret_value()) == 0

"""Tests for Qdrant configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from nohiki_qdrant_client import QdrantMixin, QdrantSettings
from nohiki_qdrant_client.config import QdrantMixin as _QdrantMixinDirect
from pydantic import SecretStr


class TestQdrantSettings:
    """Tests for QdrantSettings class."""

    def test_default_values(self) -> None:
        """Test default settings values."""
        settings = QdrantSettings()
        assert settings.host == "qdrant"
        assert settings.grpc_port == 6334
        assert settings.api_key is None
        assert settings.timeout_seconds == 10
        assert settings.use_tls is False

    def test_custom_values(self) -> None:
        """Test custom settings via constructor."""
        settings = QdrantSettings(
            host="custom-host",
            grpc_port=7334,
            api_key=SecretStr("test-api-key"),
        )
        assert settings.host == "custom-host"
        assert settings.grpc_port == 7334
        assert settings.api_key is not None
        assert settings.api_key.get_secret_value() == "test-api-key"

    def test_timeout_seconds_bounds(self) -> None:
        """Test timeout_seconds min/max constraints."""
        settings = QdrantSettings(timeout_seconds=300)
        assert settings.timeout_seconds == 300

        with pytest.raises(ValueError, match="greater than or equal to 1"):
            QdrantSettings(timeout_seconds=0)

        with pytest.raises(ValueError, match="less than or equal to 300"):
            QdrantSettings(timeout_seconds=301)

    def test_host_min_length(self) -> None:
        """Test host must be non-empty."""
        with pytest.raises(ValueError, match="at least 1"):
            QdrantSettings(host="")

    def test_grpc_port_bounds(self) -> None:
        """Test grpc_port min/max constraints."""
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            QdrantSettings(grpc_port=0)

        with pytest.raises(ValueError, match="less than or equal to 65535"):
            QdrantSettings(grpc_port=70000)

    def test_no_removed_fields(self) -> None:
        """Test that deprecated fields are not present."""
        settings = QdrantSettings()
        assert not hasattr(settings, "http_port")
        assert not hasattr(settings, "prefer_grpc")
        assert not hasattr(settings, "muvera_vector_name")
        assert not hasattr(settings, "sparse_vector_name")
        assert not hasattr(settings, "colbert_vector_name")


class TestQdrantMixin:
    """Tests for QdrantMixin settings mixin."""

    def test_exported_from_package(self) -> None:
        """Test QdrantMixin is re-exported at package level."""
        assert QdrantMixin is _QdrantMixinDirect

    def test_mixin_provides_qdrant_field(self) -> None:
        """Test QdrantMixin provides a qdrant field with default factory."""
        from nohiki_core_settings import NohikiBaseSettings
        from pydantic_settings import SettingsConfigDict

        class _TestSettings(QdrantMixin, NohikiBaseSettings):
            model_config = SettingsConfigDict(env_prefix="TEST_MIXIN_")
            service_name: str = "test"
            service_version: str = "0.0.0"
            service_name_friendly: str = "Test"
            service_desc_friendly: str = "Test"

        with patch.dict(os.environ, {"TEST_MIXIN_ENVIRONMENT": "development"}, clear=False):
            settings = _TestSettings()

        assert isinstance(settings.qdrant, QdrantSettings)
        assert settings.qdrant.host == "qdrant"

    def test_mixin_requires_api_key_in_production(self) -> None:
        """Test QdrantMixin enforces API key in non-dev environments."""
        from nohiki_core_settings import NohikiBaseSettings
        from pydantic_settings import SettingsConfigDict

        class _TestSettings(QdrantMixin, NohikiBaseSettings):
            model_config = SettingsConfigDict(env_prefix="TEST_PROD_")
            service_name: str = "test"
            service_version: str = "0.0.0"
            service_name_friendly: str = "Test"
            service_desc_friendly: str = "Test"

        with (
            patch.dict(os.environ, {"TEST_PROD_ENVIRONMENT": "production"}, clear=False),
            pytest.raises(ValueError, match="QDRANT__API_KEY is required"),
        ):
            _TestSettings()

    def test_mixin_allows_no_api_key_in_dev(self) -> None:
        """Test QdrantMixin allows no API key in development."""
        from nohiki_core_settings import NohikiBaseSettings
        from pydantic_settings import SettingsConfigDict

        class _TestSettings(QdrantMixin, NohikiBaseSettings):
            model_config = SettingsConfigDict(env_prefix="TEST_DEV_")
            service_name: str = "test"
            service_version: str = "0.0.0"
            service_name_friendly: str = "Test"
            service_desc_friendly: str = "Test"

        with patch.dict(os.environ, {"TEST_DEV_ENVIRONMENT": "development"}, clear=False):
            settings = _TestSettings()

        assert settings.qdrant.api_key is None

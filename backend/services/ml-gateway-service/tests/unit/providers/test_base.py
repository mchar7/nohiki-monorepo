"""Tests for ml_gateway_service.providers.base module."""

from __future__ import annotations

import dataclasses

import pytest
from ml_gateway_service.providers.base import (
    BaseMLProvider,
    MLOperationType,
    ProviderCapabilities,
)


class TestMLOperationType:
    """Tests for MLOperationType enum."""

    def test_enum_values(self) -> None:
        """Test that enum has expected values."""
        assert MLOperationType.EMBEDDING == "embedding"
        assert MLOperationType.RERANK == "rerank"

    def test_enum_is_string(self) -> None:
        """Test that enum values are strings."""
        assert isinstance(MLOperationType.EMBEDDING.value, str)
        assert isinstance(MLOperationType.RERANK.value, str)

    def test_enum_iteration(self) -> None:
        """Test that we can iterate over all operation types."""
        operations = list(MLOperationType)
        assert len(operations) == 3
        assert MLOperationType.EMBEDDING in operations
        assert MLOperationType.RERANK in operations
        assert MLOperationType.BATCH_EMBEDDING in operations


class TestProviderCapabilities:
    """Tests for ProviderCapabilities dataclass."""

    def test_default_values(self) -> None:
        """Test default capability values."""
        caps = ProviderCapabilities()
        assert caps.supports_embedding is True
        assert caps.supports_rerank is False
        assert caps.max_batch_size == 32
        assert caps.gpu_available is False

    def test_custom_values(self) -> None:
        """Test custom capability values."""
        caps = ProviderCapabilities(
            supports_embedding=False,
            supports_rerank=True,
            max_batch_size=64,
            gpu_available=True,
        )
        assert caps.supports_embedding is False
        assert caps.supports_rerank is True
        assert caps.max_batch_size == 64
        assert caps.gpu_available is True

    def test_is_frozen_dataclass(self) -> None:
        """Test that capabilities are a frozen dataclass."""
        assert dataclasses.is_dataclass(ProviderCapabilities)
        params = getattr(ProviderCapabilities, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_slots(self) -> None:
        """Test that slots are used for memory efficiency."""
        caps = ProviderCapabilities()
        assert hasattr(caps, "__slots__")


class TestBaseMLProvider:
    """Tests for BaseMLProvider abstract class."""

    def test_cannot_instantiate_directly(self) -> None:
        """Test that BaseMLProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseMLProvider()

    def test_supports_operation_embedding(
        self,
        mock_provider: BaseMLProvider,
    ) -> None:
        """Test supports_operation for embedding."""
        assert mock_provider.supports_operation(MLOperationType.EMBEDDING) is True

    def test_supports_operation_rerank_default_false(
        self,
        mock_provider: BaseMLProvider,
    ) -> None:
        """Test supports_operation for rerank defaults to False."""
        assert mock_provider.supports_operation(MLOperationType.RERANK) is False

    def test_supports_operation_rerank_with_gpu_provider(
        self,
        mock_gpu_provider: BaseMLProvider,
    ) -> None:
        """Test supports_operation for rerank with GPU provider."""
        assert mock_gpu_provider.supports_operation(MLOperationType.RERANK) is True

    def test_default_fallback_settings(self, mock_provider: BaseMLProvider) -> None:
        """Test default_fallback_settings returns valid settings."""
        from ml_gateway_service.core.config import ProviderFallbackSettings

        settings = mock_provider.default_fallback_settings()
        assert isinstance(settings, ProviderFallbackSettings)
        assert settings.enabled is True
        assert settings.min_consecutive_errors == 3

    def test_default_enabled(self, mock_provider: BaseMLProvider) -> None:
        """Test default_enabled returns False."""
        assert mock_provider.default_enabled() is False

    def test_default_priority(self, mock_provider: BaseMLProvider) -> None:
        """Test default_priority returns 100."""
        assert mock_provider.default_priority() == 100

    def test_health_check_default(self, mock_provider: BaseMLProvider) -> None:
        """Test health_check returns True by default."""
        assert mock_provider.health_check() is True

    def test_repr(self, mock_provider: BaseMLProvider) -> None:
        """Test string representation."""
        repr_str = repr(mock_provider)
        assert "MockProvider" in repr_str
        assert "mock" in repr_str

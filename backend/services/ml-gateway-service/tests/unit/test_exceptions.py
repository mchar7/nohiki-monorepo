"""Unit tests for ml_gateway_service.exceptions module."""

from __future__ import annotations

from ml_gateway_service.exceptions import (
    MLGatewayError,
    NoProviderAvailableError,
    ProviderExecutionError,
)
from nohiki_common_exceptions import ErrorSeverity, RetryStrategy


class TestMLGatewayError:
    """Tests for MLGatewayError base class."""

    def test_creates_with_message(self) -> None:
        """MLGatewayError creates with message."""
        error = MLGatewayError("Test error")
        assert str(error) == "Test error"

    def test_has_default_severity(self) -> None:
        """MLGatewayError has HIGH severity by default."""
        error = MLGatewayError("Test error")
        assert error.severity == ErrorSeverity.HIGH

    def test_has_default_retry_strategy(self) -> None:
        """MLGatewayError has RETRY_EXPONENTIAL by default."""
        error = MLGatewayError("Test error")
        assert error.retry_strategy == RetryStrategy.RETRY_EXPONENTIAL

    def test_accepts_custom_severity(self) -> None:
        """MLGatewayError accepts custom severity."""
        error = MLGatewayError("Test error", severity=ErrorSeverity.CRITICAL)
        assert error.severity == ErrorSeverity.CRITICAL

    def test_accepts_custom_retry_strategy(self) -> None:
        """MLGatewayError accepts custom retry strategy."""
        error = MLGatewayError("Test error", retry_strategy=RetryStrategy.NO_RETRY)
        assert error.retry_strategy == RetryStrategy.NO_RETRY

    def test_accepts_context_kwargs(self) -> None:
        """MLGatewayError accepts context kwargs."""
        error = MLGatewayError("Test error", provider="modal", operation="embedding")
        assert error.context["provider"] == "modal"
        assert error.context["operation"] == "embedding"


class TestNoProviderAvailableError:
    """Tests for NoProviderAvailableError."""

    def test_creates_with_operation(self) -> None:
        """NoProviderAvailableError creates with operation."""
        error = NoProviderAvailableError("embedding")
        assert "embedding" in str(error)
        assert "No provider available" in str(error)

    def test_has_operation_in_context(self) -> None:
        """NoProviderAvailableError has operation in context."""
        error = NoProviderAvailableError("rerank")
        assert error.context["operation"] == "rerank"

    def test_has_high_severity(self) -> None:
        """NoProviderAvailableError has HIGH severity."""
        error = NoProviderAvailableError("embedding")
        assert error.severity == ErrorSeverity.HIGH

    def test_has_exponential_retry(self) -> None:
        """NoProviderAvailableError has RETRY_EXPONENTIAL strategy."""
        error = NoProviderAvailableError("embedding")
        assert error.retry_strategy == RetryStrategy.RETRY_EXPONENTIAL


class TestProviderExecutionError:
    """Tests for ProviderExecutionError."""

    def test_creates_with_all_params(self) -> None:
        """ProviderExecutionError creates with all parameters."""
        error = ProviderExecutionError("modal", "embedding", "Connection timeout")
        assert "modal" in str(error)
        assert "embedding" in str(error)
        assert "Connection timeout" in str(error)

    def test_has_provider_name_in_context(self) -> None:
        """ProviderExecutionError has provider_name in context."""
        error = ProviderExecutionError("kubernetes", "rerank", "OOM")
        assert error.context["provider_name"] == "kubernetes"

    def test_has_operation_in_context(self) -> None:
        """ProviderExecutionError has operation in context."""
        error = ProviderExecutionError("modal", "query_encode", "Rate limited")
        assert error.context["operation"] == "query_encode"

    def test_has_error_in_context(self) -> None:
        """ProviderExecutionError has error details in context."""
        error = ProviderExecutionError("modal", "embedding", "GPU unavailable")
        assert error.context["error"] == "GPU unavailable"

    def test_has_high_severity(self) -> None:
        """ProviderExecutionError has HIGH severity."""
        error = ProviderExecutionError("modal", "embedding", "error")
        assert error.severity == ErrorSeverity.HIGH

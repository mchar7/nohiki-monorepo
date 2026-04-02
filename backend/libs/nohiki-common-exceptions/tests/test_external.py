"""Tests for external service exceptions."""

import math

from nohiki_common_exceptions import (
    ErrorSeverity,
    ExternalServiceError,
    RateLimitedError,
    RetryStrategy,
)


class TestExternalServiceError:
    """Tests for ExternalServiceError."""

    def test_auto_generates_message(self) -> None:
        """Test message is auto-generated from service details."""
        error = ExternalServiceError(
            service_name="job-storage-service",
            operation="GetJob",
        )

        assert str(error) == "Call to job-storage-service.GetJob() failed"

    def test_custom_message_preserved(self) -> None:
        """Test custom message overrides auto-generated one."""
        error = ExternalServiceError(
            message="Connection timeout to job-store",
            service_name="job-storage-service",
            operation="GetJob",
        )

        assert str(error) == "Connection timeout to job-store"

    def test_captures_original_error(self) -> None:
        """Test original exception is captured in context."""
        original = ConnectionError("Connection refused")
        error = ExternalServiceError(
            service_name="notification-service",
            operation="SendEmail",
            original_error=original,
        )
        ctx = error.to_log_context()

        assert ctx["original_error_type"] == "ConnectionError"
        assert ctx["original_error_message"] == "Connection refused"
        assert error.original_error is original

    def test_original_error_none_handling(self) -> None:
        """Test context handles None original_error."""
        error = ExternalServiceError(
            service_name="service",
            operation="method",
        )
        ctx = error.to_log_context()

        assert ctx["original_error_type"] is None
        assert ctx["original_error_message"] is None

    def test_is_retryable(self) -> None:
        """Test ExternalServiceError is retryable by default."""
        error = ExternalServiceError(
            service_name="service",
            operation="call",
        )

        assert error.is_retryable is True
        assert error.retry_strategy == RetryStrategy.RETRY_EXPONENTIAL

    def test_severity_is_high(self) -> None:
        """Test severity is HIGH for external service errors."""
        error = ExternalServiceError(
            service_name="service",
            operation="call",
        )

        assert error.severity == ErrorSeverity.HIGH

    def test_context_includes_service_details(self) -> None:
        """Test context contains service name and operation."""
        error = ExternalServiceError(
            service_name="notification-service",
            operation="SendEmail",
        )
        ctx = error.to_log_context()

        assert ctx["service_name"] == "notification-service"
        assert ctx["operation"] == "SendEmail"


class TestRateLimitedError:
    """Tests for RateLimitedError."""

    def test_auto_generates_message(self) -> None:
        """Test message is auto-generated from service name."""
        error = RateLimitedError(service_name="openai-api")

        assert str(error) == "Rate limited by openai-api"

    def test_message_includes_retry_after(self) -> None:
        """Test message includes retry_after when provided."""
        error = RateLimitedError(
            service_name="openai-api",
            retry_after_seconds=30.5,
        )

        assert "Rate limited by openai-api" in str(error)
        assert "retry after 30.5s" in str(error)

    def test_uses_linear_backoff(self) -> None:
        """Test RateLimitedError uses RETRY_LINEAR strategy."""
        error = RateLimitedError(service_name="api")

        assert error.is_retryable is True
        assert error.retry_strategy == RetryStrategy.RETRY_LINEAR

    def test_severity_is_medium(self) -> None:
        """Test severity is MEDIUM for rate limiting."""
        error = RateLimitedError(service_name="api")

        assert error.severity == ErrorSeverity.MEDIUM

    def test_context_includes_retry_after_seconds(self) -> None:
        """Test context contains retry_after_seconds."""
        error = RateLimitedError(
            service_name="stripe-api",
            retry_after_seconds=60.0,
        )
        ctx = error.to_log_context()

        assert ctx["service_name"] == "stripe-api"
        assert math.isclose(ctx["retry_after_seconds"], 60.0)

    def test_retry_after_none_in_context(self) -> None:
        """Test retry_after_seconds can be None."""
        error = RateLimitedError(service_name="unknown-api")
        ctx = error.to_log_context()

        assert ctx["retry_after_seconds"] is None

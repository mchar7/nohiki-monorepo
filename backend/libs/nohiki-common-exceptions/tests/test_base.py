"""Tests for base exception classes."""

import pytest
from nohiki_common_exceptions import (
    ErrorSeverity,
    NohikiError,
    RetryStrategy,
)


class TestErrorSeverity:
    """Tests for ErrorSeverity enum."""

    def test_all_values_exist(self) -> None:
        """Verify all severity levels are defined."""
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"

    def test_enum_count(self) -> None:
        """Verify exactly 4 severity levels exist."""
        assert len(ErrorSeverity) == 4


class TestRetryStrategy:
    """Tests for RetryStrategy enum."""

    def test_all_values_exist(self) -> None:
        """Verify all retry strategies are defined."""
        assert RetryStrategy.NO_RETRY.value == "no_retry"
        assert RetryStrategy.RETRY_IMMEDIATE.value == "immediate"
        assert RetryStrategy.RETRY_EXPONENTIAL.value == "exponential"
        assert RetryStrategy.RETRY_LINEAR.value == "linear"

    def test_enum_count(self) -> None:
        """Verify exactly 4 retry strategies exist."""
        assert len(RetryStrategy) == 4


class TestNohikiError:
    """Tests for NohikiError base class."""

    def test_initialization_with_message_only(self) -> None:
        """Test creating error with just a message uses defaults."""
        error = NohikiError(message="Something went wrong")

        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.retry_strategy == RetryStrategy.RETRY_EXPONENTIAL
        assert error.context == {}

    def test_initialization_with_all_parameters(self) -> None:
        """Test creating error with all parameters."""
        context = {"key": "value", "count": 42}
        error = NohikiError(
            message="Custom error",
            severity=ErrorSeverity.CRITICAL,
            retry_strategy=RetryStrategy.NO_RETRY,
            context=context,
        )

        assert error.message == "Custom error"
        assert error.severity == ErrorSeverity.CRITICAL
        assert error.retry_strategy == RetryStrategy.NO_RETRY
        assert error.context == {"key": "value", "count": 42}

    def test_is_retryable_for_no_retry(self) -> None:
        """Test is_retryable returns False for NO_RETRY strategy."""
        error = NohikiError(
            message="Not retryable",
            retry_strategy=RetryStrategy.NO_RETRY,
        )
        assert error.is_retryable is False

    def test_is_retryable_for_immediate(self) -> None:
        """Test is_retryable returns True for RETRY_IMMEDIATE strategy."""
        error = NohikiError(
            message="Retryable",
            retry_strategy=RetryStrategy.RETRY_IMMEDIATE,
        )
        assert error.is_retryable is True

    def test_is_retryable_for_exponential(self) -> None:
        """Test is_retryable returns True for RETRY_EXPONENTIAL strategy."""
        error = NohikiError(
            message="Retryable",
            retry_strategy=RetryStrategy.RETRY_EXPONENTIAL,
        )
        assert error.is_retryable is True

    def test_is_retryable_for_linear(self) -> None:
        """Test is_retryable returns True for RETRY_LINEAR strategy."""
        error = NohikiError(
            message="Retryable",
            retry_strategy=RetryStrategy.RETRY_LINEAR,
        )
        assert error.is_retryable is True

    def test_to_log_context_basic(self) -> None:
        """Test to_log_context includes all base fields."""
        error = NohikiError(message="Test error")
        ctx = error.to_log_context()

        assert ctx["error_type"] == "NohikiError"
        assert ctx["error_message"] == "Test error"
        assert ctx["severity"] == "medium"
        assert ctx["retry_strategy"] == "exponential"

    def test_to_log_context_includes_custom_context(self) -> None:
        """Test to_log_context merges custom context."""
        error = NohikiError(
            message="Test error",
            context={"request_id": "abc-123", "user_id": "user-456"},
        )
        ctx = error.to_log_context()

        assert ctx["request_id"] == "abc-123"
        assert ctx["user_id"] == "user-456"
        assert ctx["error_type"] == "NohikiError"

    def test_exception_inheritance(self) -> None:
        """Test NohikiError inherits from Exception."""
        error = NohikiError(message="Test")
        assert isinstance(error, Exception)

    def test_exception_can_be_raised_and_caught(self) -> None:
        """Test error can be raised and caught."""
        with pytest.raises(NohikiError, match="Raised error"):
            raise NohikiError(message="Raised error")

    def test_context_is_mutable(self) -> None:
        """Test context dict can be modified after creation."""
        error = NohikiError(message="Test")
        error.context["added_later"] = "new value"

        assert error.context["added_later"] == "new value"
        assert error.to_log_context()["added_later"] == "new value"

    def test_str_representation(self) -> None:
        """Test __str__ returns the message."""
        error = NohikiError(message="Human readable message")
        assert str(error) == "Human readable message"

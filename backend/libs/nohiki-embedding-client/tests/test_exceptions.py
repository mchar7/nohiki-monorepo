"""Tests for nohiki_embedding_client.exceptions module."""

from __future__ import annotations

from nohiki_common_exceptions import ErrorSeverity, RetryStrategy
from nohiki_embedding_client.exceptions import (
    EmbeddingError,
    EmbeddingFailedError,
)


class TestEmbeddingError:
    """Tests for EmbeddingError base class."""

    def test_basic_initialization(self) -> None:
        """Test basic error initialization."""
        error = EmbeddingError(
            message="Test error message",
            request_id="req-123",
            entity_id="entity-456",
        )

        assert str(error) == "Test error message"
        assert error.request_id == "req-123"
        assert error.entity_id == "entity-456"
        assert error.severity == ErrorSeverity.HIGH
        assert error.retry_strategy == RetryStrategy.RETRY_EXPONENTIAL

    def test_default_values(self) -> None:
        """Test error with default values."""
        error = EmbeddingError(message="Simple error")

        assert str(error) == "Simple error"
        assert error.request_id is None
        assert error.entity_id is None

    def test_custom_severity_and_retry(self) -> None:
        """Test error with custom severity and retry strategy."""
        error = EmbeddingError(
            message="Custom error",
            severity=ErrorSeverity.LOW,
            retry_strategy=RetryStrategy.NO_RETRY,
        )

        assert error.severity == ErrorSeverity.LOW
        assert error.retry_strategy == RetryStrategy.NO_RETRY

    def test_is_retryable_property(self) -> None:
        """Test is_retryable property inherited from NohikiError."""
        retryable_error = EmbeddingError(
            message="Retryable",
            retry_strategy=RetryStrategy.RETRY_EXPONENTIAL,
        )
        non_retryable_error = EmbeddingError(
            message="Non-retryable",
            retry_strategy=RetryStrategy.NO_RETRY,
        )

        assert retryable_error.is_retryable is True
        assert non_retryable_error.is_retryable is False


class TestEmbeddingFailedError:
    """Tests for EmbeddingFailedError."""

    def test_initialization(self) -> None:
        """Test failed error initialization."""
        error = EmbeddingFailedError(
            request_id="failed-req-123",
            error_message="Model overloaded",
            error_code="MODEL_OVERLOAD",
            entity_id="entity-abc",
            retryable=True,
        )

        assert "Model overloaded" in str(error)
        assert "MODEL_OVERLOAD" in str(error)
        assert error.request_id == "failed-req-123"
        assert error.entity_id == "entity-abc"
        assert error.error_code == "MODEL_OVERLOAD"
        assert error.original_message == "Model overloaded"
        assert error.retryable is True

    def test_retryable_sets_retry_strategy(self) -> None:
        """Test that retryable flag sets appropriate retry strategy."""
        retryable_error = EmbeddingFailedError(
            request_id="req",
            error_message="Temporary failure",
            error_code="TEMP_ERROR",
            retryable=True,
        )
        non_retryable_error = EmbeddingFailedError(
            request_id="req",
            error_message="Permanent failure",
            error_code="PERM_ERROR",
            retryable=False,
        )

        assert retryable_error.is_retryable is True
        assert retryable_error.retry_strategy == RetryStrategy.RETRY_EXPONENTIAL

        assert non_retryable_error.is_retryable is False
        assert non_retryable_error.retry_strategy == RetryStrategy.NO_RETRY

    def test_default_not_retryable(self) -> None:
        """Test that default retryable is False."""
        error = EmbeddingFailedError(
            request_id="req",
            error_message="Error",
            error_code="ERR",
        )

        assert error.retryable is False
        assert error.is_retryable is False

    def test_without_entity_id(self) -> None:
        """Test failed error without entity_id."""
        error = EmbeddingFailedError(
            request_id="req",
            error_message="Error",
            error_code="ERR",
        )

        assert error.entity_id is None

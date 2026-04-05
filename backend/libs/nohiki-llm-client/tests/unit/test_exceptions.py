"""Unit tests for LLM exceptions."""

from __future__ import annotations

from nohiki_llm_client import (
    LLMAuthenticationError,
    LLMCircuitOpenError,
    LLMContextTooLongError,
    LLMError,
    LLMInvalidSchemaError,
    LLMProviderResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransientError,
    LLMValidationError,
)


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_base_error_is_exception(self) -> None:
        """LLMError inherits from Exception."""
        assert issubclass(LLMError, Exception)

    def test_transient_error_inherits_llm_error(self) -> None:
        """LLMTransientError inherits from LLMError."""
        assert issubclass(LLMTransientError, LLMError)

    def test_rate_limit_is_transient(self) -> None:
        """LLMRateLimitError is transient."""
        assert issubclass(LLMRateLimitError, LLMTransientError)

    def test_timeout_is_transient(self) -> None:
        """LLMTimeoutError is transient."""
        assert issubclass(LLMTimeoutError, LLMTransientError)

    def test_circuit_open_is_not_transient(self) -> None:
        """LLMCircuitOpenError is NOT transient."""
        assert issubclass(LLMCircuitOpenError, LLMError)
        assert not issubclass(LLMCircuitOpenError, LLMTransientError)

    def test_context_too_long_is_not_transient(self) -> None:
        """LLMContextTooLongError is NOT transient."""
        assert issubclass(LLMContextTooLongError, LLMError)
        assert not issubclass(LLMContextTooLongError, LLMTransientError)

    def test_authentication_is_not_transient(self) -> None:
        """LLMAuthenticationError is NOT transient."""
        assert issubclass(LLMAuthenticationError, LLMError)
        assert not issubclass(LLMAuthenticationError, LLMTransientError)

    def test_invalid_schema_is_not_transient(self) -> None:
        """LLMInvalidSchemaError is NOT transient."""
        assert issubclass(LLMInvalidSchemaError, LLMError)
        assert not issubclass(LLMInvalidSchemaError, LLMTransientError)

    def test_validation_error_is_not_transient(self) -> None:
        """LLMValidationError is NOT transient: routes to DLQ, not retry."""
        assert issubclass(LLMValidationError, LLMError)
        assert not issubclass(LLMValidationError, LLMTransientError)

    def test_validation_error_can_be_caught_as_llm_error(self) -> None:
        """LLMValidationError is catchable as the base LLMError."""
        err = LLMValidationError("Exceeded maximum retries (3) for output validation")
        assert isinstance(err, LLMError)
        assert str(err) == "Exceeded maximum retries (3) for output validation"

    def test_provider_response_error_is_not_transient(self) -> None:
        """LLMProviderResponseError is NOT transient: routes to DLQ, not retry."""
        assert issubclass(LLMProviderResponseError, LLMError)
        assert not issubclass(LLMProviderResponseError, LLMTransientError)

    def test_provider_response_error_can_be_caught_as_llm_error(self) -> None:
        """LLMProviderResponseError is catchable as the base LLMError."""
        err = LLMProviderResponseError("Invalid response from openrouter chat completions endpoint")
        assert isinstance(err, LLMError)
        assert "Invalid response from openrouter" in str(err)


class TestRateLimitError:
    """Tests for LLMRateLimitError."""

    def test_stores_retry_after(self) -> None:
        """Stores retry_after value."""
        error = LLMRateLimitError("Rate limited", retry_after=60)
        assert error.retry_after == 60

    def test_retry_after_optional(self) -> None:
        """retry_after defaults to None."""
        error = LLMRateLimitError("Rate limited")
        assert error.retry_after is None

    def test_message_preserved(self) -> None:
        """Error message is preserved."""
        error = LLMRateLimitError("Custom message", retry_after=30)
        assert str(error) == "Custom message"

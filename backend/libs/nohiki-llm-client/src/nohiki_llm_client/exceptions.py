"""LLM-specific exceptions.

These exceptions integrate with the nohiki-common-exceptions retry classification
system. Transient errors trigger Kafka retries; non-transient errors go to DLQ.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base exception for LLM operations."""


class LLMTransientError(LLMError):
    """Transient error that can be retried.

    Subclasses of this exception will trigger retry logic in the LLMClient.
    """


class LLMRateLimitError(LLMTransientError):
    """Rate limit exceeded.

    The LLM provider has rate-limited the request. Retry after backoff.
    """

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        """Initialize rate limit error.

        Args:
            message: Error message.
            retry_after: Optional seconds to wait before retrying.

        """
        super().__init__(message)
        self.retry_after = retry_after


class LLMApplicationRateLimitError(LLMRateLimitError):
    """Embedded provider rate limit that is safe to retry at the application layer.

    HTTP transport rate limits are already retried by the provider transport and
    must not be retried again by ``LLMClient``.  Providers that return a rate
    limit inside an otherwise successful response use this subtype so the
    application retry boundary can distinguish the two paths.
    """


class LLMTimeoutError(LLMTransientError):
    """Request timeout.

    The LLM provider did not respond within the configured timeout.
    """


class LLMCircuitOpenError(LLMError):
    """Circuit breaker is open.

    Too many recent failures; requests are being rejected to protect the system.
    This is NOT retryable until the circuit closes.
    """


class LLMContextTooLongError(LLMError):
    """Context exceeds model limits.

    The input prompt/context is too large for the selected model.
    NOT retryable - requires reducing input size.
    """


class LLMAuthenticationError(LLMError):
    """Authentication failed.

    The API key is invalid or expired. NOT retryable.
    """


class LLMProviderResponseError(LLMError):
    """Provider returned an unparseable or null-field response.

    Raised when a provider (e.g., OpenRouter) returns HTTP 200 but with all
    standard ChatCompletion fields as ``None``, typically indicating the model
    does not exist on this provider or its backend routing has permanently
    failed. NOT retryable: retrying the same request will produce the same
    result. Routes to DLQ in Kafka consumers.
    """


class LLMValidationError(LLMError):
    """Model exhausted all structured output validation retries.

    PydanticAI retried the model N times with validation-error feedback but the
    model never produced a conforming output. NOT retryable...this indicates a
    prompt engineering or model capability issue, not a transient provider failure.
    Routes to DLQ in Kafka consumers.
    """


class LLMInvalidSchemaError(LLMError):
    """Structured output schema invalid.

    The Pydantic model used for structured output could not be processed.
    NOT retryable - requires fixing the output model.
    """

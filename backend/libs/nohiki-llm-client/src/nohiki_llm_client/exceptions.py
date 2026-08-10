"""LLM-specific exceptions.

These exceptions integrate with the nohiki-common-exceptions retry classification
system. Transient errors trigger Kafka retries; non-transient errors go to DLQ.
"""

from __future__ import annotations

from typing import ClassVar

from nohiki_common_exceptions import NohikiError, RetryStrategy


class LLMError(NohikiError):
    """Base exception for LLM operations."""

    _retry_strategy: ClassVar[RetryStrategy] = RetryStrategy.NO_RETRY

    def __init__(self, message: str) -> None:
        """Initialize an LLM failure with its Kafka retry strategy."""
        super().__init__(message=message, retry_strategy=self._retry_strategy)


class LLMTransientError(LLMError):
    """Transient error eligible for retry.

    ``LLMClient`` retries non-rate-limit subclasses at the application layer.
    HTTP rate limits are left to the transport and Kafka retry layers; embedded
    rate limits use ``LLMApplicationRateLimitError`` when an application retry
    is safe.
    """

    _retry_strategy = RetryStrategy.RETRY_EXPONENTIAL


class LLMRateLimitError(LLMTransientError):
    """Rate limit exceeded.

    The LLM provider has rate-limited the request. Retry after backoff.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        """Initialize rate limit error.

        Args:
            message: Error message.
            retry_after: Optional seconds to wait before retrying. Fractional because
                PydanticAI's ``ModelHTTPError.retry_after`` yields ``float | None``.

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


class LLMContentFilterError(LLMError):
    """Provider blocked the request or response on content policy.

    Permanent for the prompt as sent: the same prompt draws the same refusal, so
    retrying only multiplies spend and delays the terminal result. Routes to DLQ.
    """


class LLMConfigurationError(LLMError):
    """The agent or provider was configured in a way the library refuses.

    PydanticAI's ``UserError``: a mistake by us, not by the model or the provider.
    An output mode a model cannot support, a malformed tool definition, an empty
    ``fallback_on``. Permanent by construction, and deliberately its own class so it
    surfaces loudly instead of hiding inside a generic provider error. Retrying a
    misconfiguration only burns spend. Routes to DLQ.
    """


class LLMUsageLimitError(LLMError):
    """A configured usage limit refused the run before it could complete.

    PydanticAI's ``UsageLimitExceeded``. This is policy working as intended, not a
    provider fault: nothing is wrong upstream and nothing about retrying changes the
    answer. Kept out of the transient family so no layer re-runs it, and kept separate
    from the provider-failure classes so a budget refusal is never read as an outage.
    """


class LLMInvalidSchemaError(LLMError):
    """Structured output schema invalid.

    The Pydantic model used for structured output could not be processed.
    NOT retryable - requires fixing the output model.
    """

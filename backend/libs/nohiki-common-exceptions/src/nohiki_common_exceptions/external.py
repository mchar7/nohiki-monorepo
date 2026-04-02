"""External service exceptions for Nohiki services."""

from dataclasses import dataclass

from .base import ErrorSeverity, NohikiError, RetryStrategy


@dataclass
class ExternalServiceError(NohikiError):
    """Raised when a call to another service fails.

    This exception wraps errors from external service calls (gRPC, HTTP, etc.)
    and provides context for debugging. By default, it triggers retry logic
    with exponential backoff.

    Use this exception when:
    - A gRPC call to another service fails
    - An HTTP request to an external API fails
    - Any inter-service communication error occurs

    Attributes:
        service_name: Name of the external service that failed.
        operation: The operation that was being performed.
        original_error: The underlying exception, if any.

    """

    service_name: str = ""
    operation: str = ""
    original_error: Exception | None = None

    def __post_init__(self) -> None:
        """Set default message and capture original error details."""
        if not self.message:
            self.message = f"Call to {self.service_name}.{self.operation}() failed"
        self.severity = ErrorSeverity.HIGH
        self.retry_strategy = RetryStrategy.RETRY_EXPONENTIAL
        self.context |= {
            "service_name": self.service_name,
            "operation": self.operation,
            "original_error_type": type(self.original_error).__name__ if self.original_error else None,
            "original_error_message": str(self.original_error) if self.original_error else None,
        }
        super().__post_init__()


@dataclass
class RateLimitedError(NohikiError):
    """Raised when rate-limited by an external service.

    This exception indicates the service is temporarily rejecting requests
    due to rate limiting. Uses linear backoff for retries, optionally
    honoring a retry-after header if provided.

    Use this exception when:
    - An API returns HTTP 429 Too Many Requests
    - A service indicates rate limiting in its response
    - Quota limits are temporarily exceeded

    Attributes:
        service_name: Name of the service that rate-limited us.
        retry_after_seconds: Suggested wait time before retrying, if known.

    """

    service_name: str = ""
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        """Set default message and retry behavior."""
        if not self.message:
            self.message = f"Rate limited by {self.service_name}"
            if self.retry_after_seconds is not None:
                self.message += f" (retry after {self.retry_after_seconds}s)"
        self.severity = ErrorSeverity.MEDIUM
        self.retry_strategy = RetryStrategy.RETRY_LINEAR
        self.context |= {
            "service_name": self.service_name,
            "retry_after_seconds": self.retry_after_seconds,
        }
        super().__post_init__()

"""Base exception classes and enums for Nohiki services."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorSeverity(Enum):
    """Determines alerting and logging behavior.

    Severity levels map to logging levels and alerting thresholds:
    - LOW: Log at DEBUG, no alert
    - MEDIUM: Log at WARNING, alert if frequent
    - HIGH: Log at ERROR, immediate alert
    - CRITICAL: Log at CRITICAL, page on-call
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RetryStrategy(Enum):
    """Determines how the error should be handled by Kafka/retry logic.

    - NO_RETRY: Dead-letter immediately, no retry attempts
    - RETRY_IMMEDIATE: Retry without backoff delay
    - RETRY_EXPONENTIAL: Exponential backoff between retries
    - RETRY_LINEAR: Linear backoff between retries
    """

    NO_RETRY = "no_retry"
    RETRY_IMMEDIATE = "immediate"
    RETRY_EXPONENTIAL = "exponential"
    RETRY_LINEAR = "linear"


@dataclass
class NohikiError(Exception):
    """Base error for all Nohiki services.

    All custom errors in Nohiki services should inherit from this class.
    It provides structured error information including severity levels and
    retry strategies for automatic handling by Kafka consumers.

    Attributes:
        message: Human-readable error description.
        severity: Determines logging level and alerting behavior.
        retry_strategy: Determines how Kafka handlers should retry on failure.
        context: Additional context for structured logging.

    """

    message: str = ""
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    retry_strategy: RetryStrategy = RetryStrategy.RETRY_EXPONENTIAL
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize the exception with the message."""
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return the exception message."""
        return self.message

    @property
    def is_retryable(self) -> bool:
        """Return True if this exception should trigger retry logic."""
        return self.retry_strategy != RetryStrategy.NO_RETRY

    def to_log_context(self) -> dict[str, Any]:
        """Return context dict for structured logging.

        Returns:
            Dictionary containing error type, message, severity, retry strategy,
            and any additional context.

        """
        return {
            "error_type": type(self).__name__,
            "error_message": self.message,
            "severity": self.severity.value,
            "retry_strategy": self.retry_strategy.value,
            **self.context,
        }

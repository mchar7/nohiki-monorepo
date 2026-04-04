"""Exceptions for embedding client operations."""

from __future__ import annotations

from nohiki_common_exceptions import ErrorSeverity, NohikiError, RetryStrategy


class EmbeddingError(NohikiError):
    """Base exception for embedding client errors."""

    def __init__(
        self,
        message: str,
        *,
        request_id: str | None = None,
        entity_id: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.HIGH,
        retry_strategy: RetryStrategy = RetryStrategy.RETRY_EXPONENTIAL,
    ) -> None:
        """Initialize embedding error.

        Args:
            message: Human-readable error message.
            request_id: Request identifier for correlation.
            entity_id: Entity identifier being processed.
            severity: Error severity level.
            retry_strategy: Retry strategy for this error.

        """
        super().__init__(
            message=message,
            severity=severity,
            retry_strategy=retry_strategy,
        )
        self.request_id = request_id
        self.entity_id = entity_id


class EmbeddingFailedError(EmbeddingError):
    """Raised when embedding computation fails on the compute side."""

    def __init__(
        self,
        request_id: str,
        error_message: str,
        error_code: str,
        *,
        entity_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        """Initialize failure error.

        Args:
            request_id: Request identifier that failed.
            error_message: Error message from compute service.
            error_code: Error code from compute service.
            entity_id: Entity identifier being processed.
            retryable: Whether the error is retryable.

        """
        retry_strategy = RetryStrategy.RETRY_EXPONENTIAL if retryable else RetryStrategy.NO_RETRY
        super().__init__(
            message=f"Embedding failed: {error_message} (code: {error_code})",
            request_id=request_id,
            entity_id=entity_id,
            severity=ErrorSeverity.HIGH,
            retry_strategy=retry_strategy,
        )
        self.error_code = error_code
        self.original_message = error_message
        self.retryable = retryable

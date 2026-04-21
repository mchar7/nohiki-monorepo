"""ML Gateway service exceptions."""

from __future__ import annotations

from nohiki_common_exceptions import ErrorSeverity, NohikiError, RetryStrategy


class MLGatewayError(NohikiError):
    """Base exception for ML gateway errors."""

    def __init__(
        self,
        message: str,
        *,
        severity: ErrorSeverity = ErrorSeverity.HIGH,
        retry_strategy: RetryStrategy = RetryStrategy.RETRY_EXPONENTIAL,
        **context: str | float | bool,
    ) -> None:
        """Initialize ML gateway error with message and context."""
        super().__init__(
            message=message,
            severity=severity,
            retry_strategy=retry_strategy,
            context=context,
        )


class NoProviderAvailableError(MLGatewayError):
    """No provider available to handle request."""

    def __init__(self, operation: str) -> None:
        """Initialize with the operation that has no provider."""
        super().__init__(
            message=f"No provider available for {operation}",
            severity=ErrorSeverity.HIGH,
            retry_strategy=RetryStrategy.RETRY_EXPONENTIAL,
            operation=operation,
        )


class ProviderExecutionError(MLGatewayError):
    """Provider failed to execute request."""

    def __init__(
        self,
        provider_name: str,
        operation: str,
        error: str,
    ) -> None:
        """Initialize with provider name, operation, and error details."""
        super().__init__(
            message=f"Provider {provider_name} failed {operation}: {error}",
            severity=ErrorSeverity.HIGH,
            retry_strategy=RetryStrategy.RETRY_EXPONENTIAL,
            provider_name=provider_name,
            operation=operation,
            error=error,
        )

"""Service-specific exceptions extending Nohiki exception hierarchy."""

from __future__ import annotations

from nohiki_common_exceptions import (
    DataNotAvailableError,
    ExternalServiceError,
    NohikiError,
    RetryStrategy,
)


class DocProcessError(NohikiError):
    """Base exception for document processing operations."""


class ProviderUnavailableError(ExternalServiceError):
    """Processing provider is not available.

    Retryable with exponential backoff.
    """

    def __init__(self, provider: str) -> None:
        """Initialize provider unavailable error.

        Args:
            provider: Name of the unavailable provider.

        """
        super().__init__(
            service_name=provider,
            operation="health_check",
            message=f"Processing provider '{provider}' is unavailable",
        )
        self.provider = provider


class ProcessingTimeoutError(ExternalServiceError):
    """Processing exceeded configured timeout.

    Retryable with exponential backoff.
    """

    def __init__(self, task_id: str, timeout_seconds: float) -> None:
        """Initialize processing timeout error.

        Args:
            task_id: ID of the timed-out task.
            timeout_seconds: Configured timeout in seconds.

        """
        super().__init__(
            service_name="docling",
            operation="process",
            message=f"Task {task_id} timed out after {timeout_seconds}s",
        )
        self.task_id = task_id
        self.timeout_seconds = timeout_seconds


class DocumentNotFoundError(DataNotAvailableError):
    """Source document not found in S3.

    Not retryable - document does not exist.
    """

    def __init__(self, storage_key: str) -> None:
        """Initialize document not found error.

        Args:
            storage_key: S3 storage key of the missing document.

        """
        super().__init__(
            resource_type="Document",
            resource_id=storage_key,
            source="s3",
        )
        self.storage_key = storage_key
        self._retry_strategy = RetryStrategy.NO_RETRY


class ContentNotFoundError(DataNotAvailableError):
    """Requested content not found in cache.

    Not retryable - content does not exist.
    """

    def __init__(self, content_id: str) -> None:
        """Initialize content not found error.

        Args:
            content_id: ID of the missing content.

        """
        super().__init__(
            resource_type="ProcessedContent",
            resource_id=content_id,
            source="cache",
        )
        self.content_id = content_id
        self._retry_strategy = RetryStrategy.NO_RETRY


class ProviderNotInstalledError(DocProcessError):
    """Provider dependencies not installed.

    Not retryable - configuration error.
    """

    def __init__(self, provider: str, install_hint: str) -> None:
        """Initialize provider not installed error.

        Args:
            provider: Name of the missing provider.
            install_hint: Installation command hint.

        """
        super().__init__(f"{provider} not installed. Install with: {install_hint}")
        self.provider = provider
        self.install_hint = install_hint
        self._retry_strategy = RetryStrategy.NO_RETRY

"""Protocol defining the interface for document processing backends."""

from __future__ import annotations

from typing import Protocol

from doc_process_service.models.domain import ProcessingOptions, ProcessingResult


class ProcessingProvider(Protocol):
    """Protocol for document processing backends."""

    @property
    def name(self) -> str:
        """Provider identifier for logging and metrics."""
        ...

    def is_available(self) -> bool:
        """Check if provider is ready to accept requests."""
        ...

    def process(self, content: bytes, content_id: str, options: ProcessingOptions) -> ProcessingResult:
        """Process document content synchronously.

        Args:
            content: Raw document bytes.
            content_id: Opaque identifier assigned to the document.
            options: Processing configuration.

        Returns:
            ProcessingResult with extracted content or error details.

        """
        ...

    async def process_async(
        self,
        content: bytes,
        content_id: str,
        options: ProcessingOptions,
    ) -> ProcessingResult:
        """Process document content asynchronously.

        Args:
            content: Raw document bytes.
            content_id: Opaque identifier assigned to the document.
            options: Processing configuration.

        Returns:
            ProcessingResult with extracted content or error details.

        """
        ...

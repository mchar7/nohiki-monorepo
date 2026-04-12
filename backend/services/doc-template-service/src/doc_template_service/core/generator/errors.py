"""Document generation error types."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doc_template_service.schemas.models import ValidationReport


class GenerationError(Exception):
    """Exception raised when document generation fails."""

    def __init__(
        self,
        message: str,
        validation_report: ValidationReport | None = None,
        original_error: Exception | None = None,
    ) -> None:
        """Initialize with message and optional context.

        Args:
            message: Error description
            validation_report: Validation report if validation failed
            original_error: Original exception that caused the error

        """
        super().__init__(message)
        self.validation_report = validation_report
        self.original_error = original_error

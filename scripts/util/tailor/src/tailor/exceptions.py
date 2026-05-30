"""Custom exceptions for the tailor CLI."""

from __future__ import annotations


class TailorError(Exception):
    """Base exception for all tailor errors."""

    def __init__(self, message: str) -> None:
        """Store structured message alongside the stdlib ``args`` tuple."""
        self.message = message
        super().__init__(message)


class ConfigError(TailorError):
    """Configuration error (missing API keys, invalid settings)."""


class FileLoadError(TailorError):
    """Error loading input files (context, job, template, schema)."""

    def __init__(self, message: str, path: str | None = None) -> None:
        """Attach the offending file path for downstream diagnostics."""
        self.path = path
        super().__init__(message)


class LintConfigError(TailorError):
    """Error loading or validating a lint configuration file."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        """Attach the offending config file path for diagnostics."""
        self.path = path
        super().__init__(message)


class TemplateError(TailorError):
    """Error related to template loading or metadata parsing."""


class SchemaError(TailorError):
    """Error related to schema loading or validation."""


class DataError(TailorError):
    """Error related to manual JSON data loading or validation."""


class GenerationError(TailorError):
    """Error during LLM content generation."""

    def __init__(
        self,
        message: str,
        *,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        """Capture model and provider for structured error reporting."""
        self.model = model
        self.provider = provider
        super().__init__(message)


class RenderError(TailorError):
    """Error during template rendering or output conversion."""

    def __init__(
        self,
        message: str,
        *,
        output_format: str | None = None,
    ) -> None:
        """Capture the requested format that triggered the failure."""
        self.output_format = output_format
        super().__init__(message)


class GotenbergError(TailorError):
    """Error communicating with Gotenberg service."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        """Capture the HTTP status code from the failed Gotenberg request."""
        self.status_code = status_code
        super().__init__(message)

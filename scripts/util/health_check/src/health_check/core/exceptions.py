"""Typed exception hierarchy for the health check module."""

from __future__ import annotations


class HealthCheckError(Exception):
    """Base exception for all health check module errors."""

    def __init__(self, message: str) -> None:
        """Initialise with a descriptive error message."""
        self.message = message
        super().__init__(message)


class PlatformError(HealthCheckError):
    """Error arising from platform-level operations (container runtime, kubectl, etc.)."""


class RuntimeDetectionError(PlatformError):
    """No supported container runtime (docker/podman) or kubectl found in PATH."""


class CheckExecutionError(HealthCheckError):
    """Unexpected error during check execution that was not caught by the check itself."""

    def __init__(self, message: str, *, check_id: str) -> None:
        """Initialise with error message and the ID of the failing check."""
        self.check_id = check_id
        super().__init__(message)


class DependencyCycleError(HealthCheckError):
    """Circular dependency detected in the check dependency graph."""


class ConfigurationError(HealthCheckError):
    """Invalid, missing, or inconsistent configuration."""

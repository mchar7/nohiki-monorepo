"""Core data models, base classes, registry, and runner for health checks."""

from __future__ import annotations

from health_check.core.base import HealthCheck
from health_check.core.exceptions import (
    CheckExecutionError,
    ConfigurationError,
    DependencyCycleError,
    HealthCheckError,
    PlatformError,
    RuntimeDetectionError,
)
from health_check.core.models import (
    CheckCategory,
    CheckMetadata,
    CheckResult,
    CheckStatus,
    CheckSuiteResult,
    FixResult,
    FixStatus,
    RemediationResult,
)
from health_check.core.registry import CheckRegistry
from health_check.core.runner import CheckRunner

__all__ = [
    "CheckCategory",
    "CheckExecutionError",
    "CheckMetadata",
    "CheckRegistry",
    "CheckResult",
    "CheckRunner",
    "CheckStatus",
    "CheckSuiteResult",
    "ConfigurationError",
    "DependencyCycleError",
    "FixResult",
    "FixStatus",
    "HealthCheck",
    "HealthCheckError",
    "PlatformError",
    "RemediationResult",
    "RuntimeDetectionError",
]

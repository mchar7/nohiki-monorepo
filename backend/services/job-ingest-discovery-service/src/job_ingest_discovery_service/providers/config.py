"""Provider configuration models.

Defines configuration for provider registration, priority, and fallback behavior.
All provider-specific settings should be defined within each provider's directory,
not here. This module only defines the generic configuration structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FallbackTrigger(Enum):
    """Conditions that can trigger fallback to another provider."""

    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class FallbackConfig:
    """Configuration for provider fallback behavior.

    Attributes:
        enabled: Whether fallback is enabled for this provider
        rate_limit_wait_threshold_seconds: If rate limit wait time exceeds this,
            trigger fallback. Set to 0 to never fallback on rate limits.
        error_duration_threshold_seconds: Consecutive error duration before fallback.
            Must account for gaps between API calls.
        min_consecutive_errors: Minimum consecutive errors before considering fallback.

    """

    enabled: bool = False
    rate_limit_wait_threshold_seconds: int = 1800  # 30 minutes default
    error_duration_threshold_seconds: int = 300  # 5 minutes default
    min_consecutive_errors: int = 3


@dataclass(slots=True)
class ProviderConfig:
    """Configuration for a single provider.

    Attributes:
        name: Provider identifier (must match provider.name property)
        enabled: Whether this provider is enabled
        priority: Lower values = higher priority (checked first)
        sources: Which sources this provider handles (if empty, uses provider's default)
        fallback: Fallback configuration for this provider

    """

    name: str
    enabled: bool = True
    priority: int = 100
    sources: list[str] = field(default_factory=list)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)


@dataclass(slots=True)
class ProviderRegistryConfig:
    """Configuration for the provider registry.

    Attributes:
        providers: List of provider configurations
        allow_multiple_per_source: If True, multiple providers can handle same source

    """

    providers: list[ProviderConfig] = field(default_factory=list)
    allow_multiple_per_source: bool = True

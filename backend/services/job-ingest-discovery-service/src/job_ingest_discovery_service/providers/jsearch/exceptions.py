"""Exceptions for JSearch provider.

Provides specific exception types for JSearch API errors.
"""

from __future__ import annotations

from nohiki_common_exceptions import RateLimitedError

from .constants import SERVICE_NAME

# Tier names for error messages
_TIER_MONTHLY = "monthly"
_TIER_HOURLY = "hourly"


class JSearchError(Exception):
    """Base exception for JSearch provider errors."""

    def __init__(self, message: str) -> None:
        """Initialize with message."""
        super().__init__(message)
        self.message = message


class JSearchNotConfiguredError(JSearchError):
    """Raised when JSearch client is not properly configured."""

    def __init__(self) -> None:
        """Initialize with standard message."""
        super().__init__(f"{SERVICE_NAME} client not configured (missing API key or disabled)")


class JSearchRateLimitError(RateLimitedError):
    """Raised when JSearch API rate limit is exceeded."""

    tier_name: str = ""

    def __init__(self, tier_name: str, retry_after_seconds: float | None = None) -> None:
        """Initialize rate limit error.

        Args:
            tier_name: Which limit tier was exceeded (e.g., "monthly", "hourly")
            retry_after_seconds: Seconds until the limit resets

        """
        super().__init__(
            message=f"{SERVICE_NAME} API {tier_name} rate limit exceeded",
            service_name=SERVICE_NAME,
            retry_after_seconds=retry_after_seconds,
        )
        self.tier_name = tier_name

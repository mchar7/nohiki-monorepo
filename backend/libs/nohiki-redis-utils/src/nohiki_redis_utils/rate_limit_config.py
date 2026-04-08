"""Rate limit configuration types with human-readable time units.

Provides convenient configuration for rate limiting with support for
multiple tiers and various time units (seconds, minutes, hours, days).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TimeUnit(Enum):
    """Time units for rate limit windows."""

    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


# Conversion factors to seconds
_UNIT_TO_SECONDS: dict[TimeUnit, int] = {
    TimeUnit.SECONDS: 1,
    TimeUnit.MINUTES: 60,
    TimeUnit.HOURS: 3600,
    TimeUnit.DAYS: 86400,
}


@dataclass(frozen=True)
class RateLimit:
    """A single rate limit specification.

    Examples:
        RateLimit(5, TimeUnit.SECONDS)      # 5 requests per second
        RateLimit(100, TimeUnit.MINUTES)    # 100 requests per minute
        RateLimit(1000, TimeUnit.HOURS)     # 1000 requests per hour
        RateLimit(200, TimeUnit.DAYS, 30)   # 200 requests per 30 days

    """

    requests: int
    unit: TimeUnit
    count: int = 1  # Number of units (e.g., 30 days)
    name: str | None = None  # Optional name for error messages

    @property
    def window_seconds(self) -> int:
        """Convert to window in seconds."""
        return _UNIT_TO_SECONDS[self.unit] * self.count

    @property
    def display_name(self) -> str:
        """Human-readable name for this limit."""
        if self.name:
            return self.name
        if self.count == 1:
            return f"{self.requests}/{self.unit.value.removesuffix('s')}"
        return f"{self.requests}/{self.count}_{self.unit.value}"


def per_second(requests: int, *, name: str | None = None) -> RateLimit:
    """Create a per-second rate limit."""
    return RateLimit(requests=requests, unit=TimeUnit.SECONDS, name=name)


def per_minute(requests: int, *, name: str | None = None) -> RateLimit:
    """Create a per-minute rate limit."""
    return RateLimit(requests=requests, unit=TimeUnit.MINUTES, name=name)


def per_hour(requests: int, *, name: str | None = None) -> RateLimit:
    """Create a per-hour rate limit."""
    return RateLimit(requests=requests, unit=TimeUnit.HOURS, name=name)


def per_day(requests: int, count: int = 1, *, name: str | None = None) -> RateLimit:
    """Create a per-day rate limit.

    Args:
        requests: Maximum requests allowed
        count: Number of days (default 1)
        name: Optional name for error messages

    """
    return RateLimit(requests=requests, unit=TimeUnit.DAYS, count=count, name=name)

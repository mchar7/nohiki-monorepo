"""Multi-tier rate limiting for external API quota management.

Provides a reusable abstraction for managing multiple rate limit tiers
(e.g., monthly + hourly quotas) with configurable behaviors per tier.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

from .rate_limiter import (
    RateLimitConfig,
    RateLimitFailurePolicy,
    RateLimitResult,
    create_rate_limiter,
)

if TYPE_CHECKING:
    from .rate_limiter import RateLimiter
    from .redis_cache import RedisCache

logger = get_logger(__name__)


class TierExceededBehavior(Enum):
    """Behavior when a rate limit tier is exceeded."""

    REJECT = "reject"  # Immediately reject the request
    LOG_ONLY = "log_only"  # Log warning but allow (for soft limits)


@dataclass(frozen=True, slots=True)
class RateLimitTier:
    """Configuration for a single rate limit tier.

    Attributes:
        name: Human-readable name for logging/errors (e.g., "monthly", "hourly")
        requests: Maximum requests allowed in the window
        window_seconds: Time window in seconds
        behavior: What to do when limit exceeded
        priority: Lower priority tiers are checked first (fail-fast on hard limits)

    """

    name: str
    requests: int
    window_seconds: int
    behavior: TierExceededBehavior = TierExceededBehavior.REJECT
    priority: int = 0


@dataclass(slots=True)
class MultiTierCheckResult:
    """Result of checking all rate limit tiers.

    Attributes:
        allowed: Whether the request is allowed (all tiers passed or soft-failed)
        exceeded_tier: Name of the tier that was exceeded (if any)
        retry_after: Seconds until the exceeded tier resets
        tier_results: Individual results for each tier (keyed by tier name)

    """

    allowed: bool
    exceeded_tier: str | None = None
    retry_after: float | None = None
    tier_results: dict[str, RateLimitResult] = field(default_factory=dict)


class MultiTierRateLimiter:
    """Rate limiter supporting multiple tiers with different quotas and behaviors.

    Useful for external APIs with multiple quota levels, e.g.:
    - 200 requests per month (hard limit)
    - 1000 requests per hour (soft limit, can queue)

    Example:
        limiter = MultiTierRateLimiter(
            cache=cache,
            key_prefix="external-api",
            tiers=[
                RateLimitTier("monthly", 200, 30*24*60*60, priority=0),
                RateLimitTier("hourly", 1000, 3600, priority=1),
            ],
        )

        result = await limiter.check("api-calls")
        if not result.allowed:
            raise RateLimitExceeded(result.exceeded_tier, result.retry_after)

    """

    def __init__(
        self,
        cache: RedisCache,
        key_prefix: str,
        tiers: list[RateLimitTier],
        failure_policy: RateLimitFailurePolicy = RateLimitFailurePolicy.FAIL_OPEN,
    ) -> None:
        """Initialize multi-tier rate limiter.

        Args:
            cache: Cache instance for storing rate limit state
            key_prefix: Prefix for rate limit keys (e.g., "jsearch:api")
            tiers: List of rate limit tiers to enforce
            failure_policy: Behavior when Redis cannot produce a valid decision

        """
        self._cache = cache
        self._key_prefix = key_prefix

        # Sort tiers by priority (lower = check first)
        self._tiers = sorted(tiers, key=lambda t: t.priority)

        # Create individual limiters for each tier
        self._limiters: dict[str, RateLimiter] = {}
        for tier in self._tiers:
            config = RateLimitConfig(
                requests=tier.requests,
                window_seconds=tier.window_seconds,
                failure_policy=failure_policy,
            )
            self._limiters[tier.name] = create_rate_limiter(cache, config)

    @property
    def tier_names(self) -> list[str]:
        """Get list of tier names in priority order."""
        return [tier.name for tier in self._tiers]

    async def check(self, key: str) -> MultiTierCheckResult:
        """Check all rate limit tiers and consume quota if allowed.

        Tiers are checked in priority order. If a tier with REJECT behavior
        is exceeded, the check stops immediately. LOG_ONLY tiers are checked
        but don't prevent the request.

        Args:
            key: Unique identifier for the rate limit bucket

        Returns:
            MultiTierCheckResult with overall status and per-tier details

        """
        tier_results: dict[str, RateLimitResult] = {}
        exceeded_tier: str | None = None
        retry_after: float | None = None

        for tier in self._tiers:
            full_key = self._build_key(tier.name, key)
            limiter = self._limiters[tier.name]

            result = await limiter.check(full_key)
            tier_results[tier.name] = result

            if not result.allowed:
                self._log_tier_exceeded(tier, result)

                if tier.behavior == TierExceededBehavior.REJECT:
                    exceeded_tier = tier.name
                    retry_after = result.retry_after
                    break

        allowed = exceeded_tier is None

        if allowed:
            self._log_check_passed(tier_results)

        return MultiTierCheckResult(
            allowed=allowed,
            exceeded_tier=exceeded_tier,
            retry_after=retry_after,
            tier_results=tier_results,
        )

    async def reset_tier(self, tier_name: str, key: str) -> None:
        """Reset a specific tier's rate limit.

        Args:
            tier_name: Name of the tier to reset
            key: Rate limit bucket key

        """
        if tier_name not in self._limiters:
            logger.warning("Unknown tier for reset", tier=tier_name)
            return

        full_key = self._build_key(tier_name, key)
        await self._limiters[tier_name].reset(full_key)
        logger.info("Rate limit tier reset", tier=tier_name, key=key)

    async def reset_all(self, key: str) -> None:
        """Reset all tiers for a given key in parallel.

        Args:
            key: Rate limit bucket key

        """
        if self._tiers:
            async with asyncio.TaskGroup() as tg:
                for tier in self._tiers:
                    tg.create_task(self.reset_tier(tier.name, key))

    def get_tier_config(self, tier_name: str) -> RateLimitTier | None:
        """Get configuration for a specific tier."""
        for tier in self._tiers:
            if tier.name == tier_name:
                return tier
        return None

    def _build_key(self, tier_name: str, key: str) -> str:
        """Build full rate limit key with prefix and tier."""
        return f"{self._key_prefix}:{tier_name}:{key}"

    def _log_tier_exceeded(self, tier: RateLimitTier, result: RateLimitResult) -> None:
        """Log when a tier is exceeded."""
        log_func = logger.warning if tier.behavior == TierExceededBehavior.REJECT else logger.info
        log_func(
            "Rate limit tier exceeded",
            tier=tier.name,
            behavior=tier.behavior.value,
            remaining=result.remaining,
            retry_after=result.retry_after,
        )

    def _log_check_passed(self, tier_results: dict[str, RateLimitResult]) -> None:
        """Log successful rate limit check with remaining quotas."""
        remaining = {name: r.remaining for name, r in tier_results.items()}
        logger.debug("Rate limit check passed", remaining=remaining)

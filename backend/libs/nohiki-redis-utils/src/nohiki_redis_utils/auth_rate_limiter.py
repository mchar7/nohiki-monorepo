"""High-level auth rate limiting abstraction.

Encapsulates the common multi-tier rate limiting pattern for authentication
endpoints (login, registration, password reset) with sensible defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

from .multi_tier_rate_limiter import (
    MultiTierCheckResult,
    MultiTierRateLimiter,
    RateLimitTier,
)
from .rate_limiter import RateLimitConfig, RateLimitFailurePolicy, create_rate_limiter

if TYPE_CHECKING:
    from .rate_limiter import RateLimiter
    from .redis_cache import RedisCache

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AuthRateLimitConfig:
    """Configuration for auth rate limiting with sensible defaults.

    All values are optional - defaults are tuned for typical auth security needs.
    """

    login_per_minute: int = 5
    login_per_hour: int = 20
    register_per_hour: int = 3
    register_per_day: int = 10
    reset_per_hour: int = 3
    max_failed_logins: int = 10
    failed_login_window_seconds: int = 3600


class AuthRateLimiter:
    """Pre-configured rate limiter for authentication endpoints.

    Provides multi-tier rate limiting for:
    - Login attempts (per-minute + per-hour to prevent brute force)
    - Registration (per-hour + per-day to prevent spam accounts)
    - Password reset (per-hour to prevent email bombing)
    - Failed login tracking

    Example:
        limiter = AuthRateLimiter.create(cache)
        await limiter.check_login("user@example.com")  # Raises if exceeded
        await limiter.check_register("203.0.113.1")  # TEST-NET-3, RFC 5737 example IP
        await limiter.record_failed_login("user@example.com")

    """

    def __init__(
        self,
        login_limiter: MultiTierRateLimiter,
        register_limiter: MultiTierRateLimiter,
        reset_limiter: RateLimiter,
        failed_login_limiter: RateLimiter,
        config: AuthRateLimitConfig,
    ) -> None:
        """Initialize with pre-configured limiters."""
        self._login_limiter = login_limiter
        self._register_limiter = register_limiter
        self._reset_limiter = reset_limiter
        self._failed_login_limiter = failed_login_limiter
        self._config = config

    @classmethod
    def create(
        cls,
        cache: RedisCache,
        config: AuthRateLimitConfig | None = None,
    ) -> AuthRateLimiter:
        """Create an AuthRateLimiter with the given cache and configuration.

        Args:
            cache: Redis cache instance
            config: Optional configuration (uses defaults if not provided)

        Returns:
            Configured AuthRateLimiter instance

        """
        cfg = config or AuthRateLimitConfig()

        login_limiter = MultiTierRateLimiter(
            cache=cache,
            key_prefix="auth:login",
            tiers=[
                RateLimitTier(
                    name="minute",
                    requests=cfg.login_per_minute,
                    window_seconds=60,
                    priority=0,
                ),
                RateLimitTier(
                    name="hour",
                    requests=cfg.login_per_hour,
                    window_seconds=3600,
                    priority=1,
                ),
            ],
            failure_policy=RateLimitFailurePolicy.FAIL_CLOSED,
        )

        register_limiter = MultiTierRateLimiter(
            cache=cache,
            key_prefix="auth:register",
            tiers=[
                RateLimitTier(
                    name="hour",
                    requests=cfg.register_per_hour,
                    window_seconds=3600,
                    priority=0,
                ),
                RateLimitTier(
                    name="day",
                    requests=cfg.register_per_day,
                    window_seconds=86400,
                    priority=1,
                ),
            ],
            failure_policy=RateLimitFailurePolicy.FAIL_CLOSED,
        )

        reset_limiter = create_rate_limiter(
            cache=cache,
            config=RateLimitConfig(
                requests=cfg.reset_per_hour,
                window_seconds=3600,
                failure_policy=RateLimitFailurePolicy.FAIL_CLOSED,
            ),
        )

        failed_login_limiter = create_rate_limiter(
            cache=cache,
            config=RateLimitConfig(
                requests=cfg.max_failed_logins,
                window_seconds=cfg.failed_login_window_seconds,
                failure_policy=RateLimitFailurePolicy.FAIL_CLOSED,
            ),
        )

        return cls(
            login_limiter=login_limiter,
            register_limiter=register_limiter,
            reset_limiter=reset_limiter,
            failed_login_limiter=failed_login_limiter,
            config=cfg,
        )

    async def check_login(self, identifier: str) -> MultiTierCheckResult:
        """Check login rate limit for an identifier (email or IP).

        Args:
            identifier: User identifier (email or IP address)

        Returns:
            MultiTierCheckResult with allowed status

        """
        result = await self._login_limiter.check(identifier)
        if not result.allowed:
            logger.warning(
                "Login rate limit exceeded",
                identifier=identifier,
                exceeded_tier=result.exceeded_tier,
                retry_after=result.retry_after,
            )
        return result

    async def check_register(self, ip: str) -> MultiTierCheckResult:
        """Check registration rate limit for an IP address.

        Args:
            ip: Client IP address

        Returns:
            MultiTierCheckResult with allowed status

        """
        result = await self._register_limiter.check(ip)
        if not result.allowed:
            logger.warning(
                "Registration rate limit exceeded",
                ip=ip,
                exceeded_tier=result.exceeded_tier,
                retry_after=result.retry_after,
            )
        return result

    async def check_password_reset(self, email: str) -> bool:
        """Check password reset rate limit.

        Args:
            email: User email

        Returns:
            True if allowed, False if rate limited

        """
        key = f"reset:{email}"
        result = await self._reset_limiter.check(key)
        if not result.allowed:
            logger.warning(
                "Password reset rate limit exceeded",
                email=email,
                retry_after=result.retry_after,
            )
        return result.allowed

    async def record_failed_login(self, identifier: str) -> int:
        """Record a failed login attempt.

        Args:
            identifier: User identifier (email or IP)

        Returns:
            Number of consecutive failures in the current window

        """
        key = f"failed:{identifier}"
        result = await self._failed_login_limiter.check(key)
        failures = self._config.max_failed_logins - result.remaining
        logger.warning("Failed login attempt", identifier=identifier, count=failures)
        return failures

    async def clear_failed_logins(self, identifier: str) -> None:
        """Clear failed login counter on successful login."""
        key = f"failed:{identifier}"
        await self._failed_login_limiter.reset(key)

    async def reset_login(self, identifier: str) -> None:
        """Reset login rate limits for an identifier."""
        await self._login_limiter.reset_all(identifier)

    async def reset_register(self, ip: str) -> None:
        """Reset registration rate limits for an IP."""
        await self._register_limiter.reset_all(ip)

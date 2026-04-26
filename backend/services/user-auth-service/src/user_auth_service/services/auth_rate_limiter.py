"""Authentication rate limiting using centralized nohiki-redis-utils."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from nohiki_observability import get_logger
from nohiki_redis_utils import (
    AuthRateLimitConfig as RedisAuthRateLimitConfig,
)
from nohiki_redis_utils import (
    AuthRateLimiter as RedisAuthRateLimiter,
)
from nohiki_redis_utils import (
    create_cache,
)

if TYPE_CHECKING:
    from user_auth_service.core.config import AuthRateLimitConfig, Settings

logger = get_logger(__name__)


class AuthRateLimiterService:
    """Service wrapper for authentication rate limiting.

    Wraps the high-level AuthRateLimiter from nohiki-redis-utils and adds
    FastAPI-specific HTTP exception handling.
    """

    def __init__(self, limiter: RedisAuthRateLimiter) -> None:
        """Initialize with the underlying rate limiter."""
        self._limiter = limiter

    @classmethod
    def create(cls, cache_name: str, redis_url: str, config: AuthRateLimitConfig) -> AuthRateLimiterService:
        """Create an AuthRateLimiterService with the given configuration."""
        cache = create_cache(cache_name, redis_url=redis_url)
        redis_config = RedisAuthRateLimitConfig(
            login_per_minute=config.login_per_minute,
            login_per_hour=config.login_per_hour,
            register_per_hour=config.register_per_hour,
            register_per_day=config.register_per_day,
            reset_per_hour=config.reset_per_hour,
        )
        limiter = RedisAuthRateLimiter.create(cache, redis_config)
        return cls(limiter)

    async def check_login(self, identifier: str) -> None:
        """Check login rate limit.

        Args:
            identifier: Email or IP address

        Raises:
            HTTPException: If rate limit exceeded

        """
        result = await self._limiter.check_login(identifier)
        if not result.allowed:
            retry_after = int(result.retry_after) if result.retry_after else 60
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    async def check_register(self, ip: str) -> None:
        """Check registration rate limit.

        Args:
            ip: Client IP address

        Raises:
            HTTPException: If rate limit exceeded

        """
        result = await self._limiter.check_register(ip)
        if not result.allowed:
            retry_after = int(result.retry_after) if result.retry_after else 3600
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many registration attempts. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    async def check_password_reset(self, email: str) -> None:
        """Check password reset rate limit.

        Args:
            email: User email

        Raises:
            HTTPException: If rate limit exceeded

        """
        allowed = await self._limiter.check_password_reset(email)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many password reset attempts. Try again in 3600 seconds.",
                headers={"Retry-After": "3600"},
            )

    async def record_failed_login(self, identifier: str) -> int:
        """Record failed login attempt and return failure count."""
        return await self._limiter.record_failed_login(identifier)

    async def clear_failed_logins(self, identifier: str) -> None:
        """Clear failed login counter on successful login."""
        await self._limiter.clear_failed_logins(identifier)


class _RateLimiterHolder:
    """Singleton holder for AuthRateLimiterService."""

    instance: AuthRateLimiterService | None = None


def get_auth_rate_limiter(settings: Settings) -> AuthRateLimiterService:
    """Get or create auth rate limiter instance."""
    if _RateLimiterHolder.instance is None:
        _RateLimiterHolder.instance = AuthRateLimiterService.create(
            cache_name=settings.service_name,
            redis_url=settings.redis.connection_string,
            config=settings.caching.rate_limit,
        )
    return _RateLimiterHolder.instance


def reset_auth_rate_limiter() -> None:
    """Reset the auth rate limiter instance (for testing)."""
    _RateLimiterHolder.instance = None

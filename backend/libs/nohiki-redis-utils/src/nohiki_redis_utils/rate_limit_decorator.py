"""Rate limiting decorator for easy integration."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from nohiki_observability import get_logger

from .rate_limiter import RateLimitConfig, create_rate_limiter


class _AsyncFunc[**P, T](Protocol):
    """Protocol for async functions with __name__ attribute."""

    __name__: str

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[T]: ...


if TYPE_CHECKING:
    from .rate_limiter import RateLimiter
    from .redis_cache import RedisCache

logger = get_logger(__name__)


def _extract_key(
    key_func: Callable[[tuple[Any, ...], dict[str, Any]], str] | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    """Extract rate limit key from function arguments."""
    if key_func is not None:
        return key_func(args, kwargs)
    if args:
        return str(args[0])
    return "default"


def _handle_rate_limit_exceeded(
    func_name: str,
    rate_key: str,
    retry_after: float | None,
    *,
    raise_on_limit: bool,
) -> None:
    """Log and optionally raise when rate limit exceeded."""
    logger.warning(
        "Rate limit exceeded",
        function=func_name,
        key=rate_key,
        retry_after=retry_after,
    )
    if raise_on_limit:
        raise RateLimitExceededError(retry_after)


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, retry_after: float | None = None) -> None:
        """Initialize exception with optional retry_after hint.

        Args:
            retry_after: Seconds until next allowed request

        """
        self.retry_after = retry_after
        msg = f"Rate limit exceeded. Retry after {retry_after}s" if retry_after else "Rate limit exceeded"
        super().__init__(msg)


def rate_limited[**P, T](
    requests: int,
    window_seconds: int,
    key_func: Callable[[tuple[Any, ...], dict[str, Any]], str] | None = None,
    *,
    cache_factory: Callable[[], RedisCache],
    raise_on_limit: bool = True,
) -> Callable[[_AsyncFunc[P, T]], Callable[P, Awaitable[T | None]]]:
    """Rate limiting decorator for async functions.

    Uses sliding window algorithm by default. Lazy-initializes cache and
    rate limiter on first call to avoid issues with event loop availability.

    Args:
        requests: Maximum requests allowed in window
        window_seconds: Time window in seconds
        key_func: Function to extract rate limit key from (args, kwargs).
                  Default: uses first positional arg as string, or "default"
        cache_factory: Factory to obtain a RedisCache instance
        raise_on_limit: If True, raise RateLimitExceeded. If False, return None.

    Returns:
        Decorated async function with rate limiting

    Example:
        @rate_limited(requests=100, window_seconds=60, key_func=lambda a, k: k.get("user_id"))
        async def api_call(user_id: str) -> dict:
            return await external_api.call()

    """

    def decorator(func: _AsyncFunc[P, T]) -> Callable[P, Awaitable[T | None]]:
        func_name = func.__name__
        _limiter: RateLimiter | None = None

        def _ensure_initialized() -> RateLimiter:
            """Lazy-initialize cache and rate limiter."""
            nonlocal _limiter
            if _limiter is not None:
                return _limiter
            cache = cache_factory()
            config = RateLimitConfig(requests=requests, window_seconds=window_seconds)
            _limiter = create_rate_limiter(cache, config)
            return _limiter

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | None:
            limiter = _ensure_initialized()
            extracted_key = _extract_key(key_func, args, kwargs)
            rate_key = f"{func_name}:{extracted_key}"
            result = await limiter.check(rate_key)

            if not result.allowed:
                _handle_rate_limit_exceeded(
                    func_name,
                    rate_key,
                    result.retry_after,
                    raise_on_limit=raise_on_limit,
                )
                return None

            return await func(*args, **kwargs)

        return wrapper

    return decorator

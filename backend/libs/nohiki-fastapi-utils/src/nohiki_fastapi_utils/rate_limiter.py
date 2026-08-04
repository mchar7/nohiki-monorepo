"""Rate limiting using the limits library (v5.4.0) with nohiki-redis-utils backend.

Rate limiting functionality for FastAPI applications using the
alisaifee/limits library instead of SlowAPI. The implementation includes:

- Custom storage adapter that integrates with nohiki-redis-utils
- FastAPI middleware for automatic rate limit enforcement
- Support for both default and per-route rate limits
- Proper error handling with informative responses

Example usage:
    from nohiki_fastapi_utils.rate_limiter import setup_rate_limiting, rate_limit

    app = FastAPI()
    setup_rate_limiting(app, default_limits=["100/minute", "1000/hour"])

    @app.get("/api/limited")
    @rate_limit("10/minute")
    async def limited_endpoint():
        return {"message": "This endpoint is rate limited"}
"""

from __future__ import annotations

import functools
import os
import time
from collections.abc import Callable
from ipaddress import ip_address, ip_network
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI, HTTPException, Request
from limits import RateLimitItem, parse
from limits.aio.storage import Storage
from nohiki_redis_utils import RedisCache, create_cache
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

RATE_LIMIT_EXCEEDED_ERROR = "Rate limit exceeded"

_JWT_AVAILABLE = False
_jwks_verifier_func: Callable[[], JWKSVerifier] | None = None
_jwks_error_class: type[Exception] = Exception

try:
    from nohiki_fastapi_utils.jwks import JWKSVerificationError, JWKSVerifier, get_jwks_verifier

    _JWT_AVAILABLE = True
    _jwks_verifier_func = get_jwks_verifier
    _jwks_error_class = JWKSVerificationError
except ImportError:
    pass

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from limits import RateLimitItem
    from starlette.requests import Request as StarletteRequest


def _cache_storage_schemes() -> list[str]:
    """Return the schemes registered by the cache storage adapter."""
    return ["cache"]


class CacheUtilsStorage(Storage):
    """Limits library storage adapter using nohiki-redis-utils.

    References:
    - https://limits.readthedocs.io/en/stable/api.html#limits.aio.storage.Storage
    - https://limits.readthedocs.io/en/stable/_modules/limits/aio/storage/base.html#Storage

    ``STORAGE_SCHEME`` matches the mutable list contract declared by the limits
    storage base class and consumed by its storage registry.

    """

    STORAGE_SCHEME: list[str] | None = _cache_storage_schemes()

    def __init__(
        self,
        service_name: str,
        *,
        redis_url: str,
        **options: object,
    ) -> None:
        """Initialize cache storage adapter.

        Args:
            service_name: Name of the service for cache namespacing
            redis_url: URL of the Redis server
            **options: Additional options passed to parent class (passed to Storage base)

        """
        super().__init__(**cast("dict[str, Any]", options))
        self.cache = create_cache(service_name, redis_url=redis_url)

    @property
    def base_exceptions(self) -> type[Exception]:
        """Return base exception type for storage operations."""
        return Exception

    async def incr(self, key: str, expiry: int, amount: int = 1) -> int:
        """Increment a counter atomically when the cache backend supports it."""
        if isinstance(self.cache, RedisCache):
            return await self.cache.incr_with_ttl_strict(key, expiry, amount)
        if callable(getattr(type(self.cache), "incr", None)):
            current = 0
            for _ in range(amount):
                current = await self.cache.incr(key)
            if current == amount:
                await self.cache.expire(key, expiry)
            return current

        current = cast("int", await self.cache.get(key) or 0)
        new_value = current + amount
        await self.cache.set(key, new_value, ttl=expiry)
        return new_value

    async def get(self, key: str) -> int:
        """Get current counter value."""
        return cast("int", await self.cache.get(key) or 0)

    async def get_expiry(self, key: str) -> float:
        """Get the counter's absolute expiry time."""
        if callable(getattr(type(self.cache), "ttl", None)):
            ttl = await self.cache.ttl(key)
            return time.time() + ttl if ttl > 0 else 0
        exists = await self.cache.exists(key)
        return time.time() + 60 if exists else 0

    async def check(self) -> bool:
        """Check if storage backend is healthy."""
        try:
            test_key = f"health_check_{time.time()}"
            await self.cache.set(test_key, "ok", ttl=1)
            result = await self.cache.get(test_key)
            await self.cache.delete(test_key)
        except OSError:
            return False
        else:
            return result == "ok"

    async def reset(self) -> int | None:
        """Reset storage (not implemented for cache backend)."""
        return None

    async def clear(self, key: str) -> None:
        """Clear specific key from storage."""
        await self.cache.delete(key)


class RateLimitExceededHTTP(HTTPException):
    """Exception raised when rate limit is exceeded."""

    def __init__(self, limit: str, retry_after: int = 60) -> None:
        """Initialize the rate limit exceeded exception."""
        super().__init__(
            status_code=429, detail=f"Rate limit exceeded: {limit}", headers={"Retry-After": str(retry_after)}
        )
        self.retry_after = retry_after


def get_client_id(request: Request) -> str:
    """Extract a client identifier for rate limiting.

    Verified JWT subjects identify authenticated clients. Anonymous clients
    use the ASGI peer address; a trusted proxy middleware may set it.
    """
    if user_id := _extract_verified_user_id(request):
        return f"user:{user_id}"

    return f"ip:{extract_client_ip(request)}"


def _extract_verified_user_id(request: Request) -> str | None:
    """Extract user ID from JWT with proper signature verification."""
    if not _JWT_AVAILABLE or _jwks_verifier_func is None:
        return None

    try:
        verifier = _jwks_verifier_func()
        if isinstance(verifier, JWKSVerifier):
            claims = verifier.verify_request(request)
        else:
            verify_request = getattr(verifier, "verify_request", None)
            if not callable(verify_request):
                return None
            claims = verify_request(request)
    except _jwks_error_class, RuntimeError:
        return None
    else:
        claim_sub = getattr(claims, "sub", None)
        return claim_sub if isinstance(claim_sub, str) else None


def extract_client_ip(request: Request, trusted_proxy_cidrs: str | tuple[str, ...] | None = None) -> str:
    """Extract the first untrusted hop from a fully validated proxy chain."""
    client_host = request.client.host if request.client else None
    if not isinstance(client_host, str):
        return "unknown"

    if trusted_proxy_cidrs is None:
        cidrs = os.getenv("NOHIKI_TRUSTED_PROXY_CIDRS", "").split(",")
    elif isinstance(trusted_proxy_cidrs, str):
        cidrs = trusted_proxy_cidrs.split(",")
    else:
        cidrs = trusted_proxy_cidrs

    forwarded_values = request.headers.get("X-Forwarded-For", "").split(",")
    if any(not hop.strip() for hop in forwarded_values) and forwarded_values != [""]:
        return client_host

    try:
        peer = ip_address(client_host)
        trusted_networks = tuple(ip_network(cidr.strip(), strict=False) for cidr in cidrs if cidr.strip())
        forwarded_hops = tuple(ip_address(hop.strip()) for hop in forwarded_values if hop.strip())
    except ValueError:
        return client_host

    current = peer
    for forwarded in reversed(forwarded_hops):
        if not any(current in network for network in trusted_networks):
            break
        current = forwarded
    return str(current)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce rate limits on requests."""

    def __init__(
        self,
        app: ASGIApp,
        storage: Storage,
        key_func: Callable[[Request], str],
        default_limits: list[str] | None = None,
    ) -> None:
        """Initialize the rate limit middleware."""
        super().__init__(app)
        self.storage = storage
        self.key_func = key_func
        self.default_limits = [parse(limit) for limit in (default_limits or [])]

    async def dispatch(self, request: StarletteRequest, call_next: Callable[..., Any]) -> Response:
        """Process request and check rate limits."""
        # Check if this endpoint has rate limiting applied
        rate_limits = getattr(request.state, "rate_limits", self.default_limits)

        if rate_limits:
            client_id = self.key_func(request)

            for limit in rate_limits:
                key = f"{client_id}:{limit.key_for()}"

                current = await self.storage.incr(key, int(limit.get_expiry()), 1)
                if current > limit.amount:
                    retry_after = max(1, int(await self.storage.get_expiry(key) - time.time()))
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": RATE_LIMIT_EXCEEDED_ERROR,
                            "message": f"Too many requests. Limit: {limit}",
                            "retry_after": retry_after,
                        },
                        headers={"Retry-After": str(retry_after)},
                    )

        response: Response = await call_next(request)
        return response


def rate_limit_exceeded_handler(_request: Request, exc: Exception) -> Response:
    """Handle rate limit exceeded exceptions.

    Args:
        request: FastAPI request object
        exc: Rate limit exceeded exception

    Returns:
        JSON response with rate limit information

    """
    if isinstance(exc, RateLimitExceededHTTP):
        return JSONResponse(
            status_code=429,
            content={
                "error": RATE_LIMIT_EXCEEDED_ERROR,
                "message": f"Too many requests. Limit: {exc.detail}",
                "retry_after": exc.retry_after,
            },
            headers={"Retry-After": str(exc.retry_after)},
        )
    return JSONResponse(
        status_code=429,
        content={"error": RATE_LIMIT_EXCEEDED_ERROR, "message": str(exc)},
    )


class RateLimitedEndpoint:
    """Wrapper for rate-limited endpoint functions."""

    _func: Callable[..., Awaitable[Any]]
    _rate_limits: list[RateLimitItem]

    def __init__(self, func: Callable[..., Awaitable[Any]], rate_limits: list[RateLimitItem]) -> None:
        """Initialize with the wrapped function and its rate limits."""
        self._func = func
        self._rate_limits = rate_limits
        functools.update_wrapper(self, func)

    @property
    def rate_limits(self) -> list[RateLimitItem]:
        """Get the rate limits for this endpoint."""
        return self._rate_limits

    async def __call__(self, *args: object, **kwargs: object) -> object:
        """Call the wrapped function."""
        return await self._func(*args, **kwargs)


def rate_limit(
    *limits: str,
) -> Callable[[Callable[..., Awaitable[Any]]], RateLimitedEndpoint]:
    """Apply rate limits to specific routes.

    Args:
        *limits: Rate limit strings (e.g., "10/minute", "100/hour")

    Example:
        @app.get("/api/endpoint")
        @rate_limit("5/minute", "50/hour")
        async def my_endpoint():
            return {"message": "Hello"}

    """
    parsed_limits: list[RateLimitItem] = [parse(limit) for limit in limits]

    def decorator(func: Callable[..., Awaitable[Any]]) -> RateLimitedEndpoint:
        return RateLimitedEndpoint(func, parsed_limits)

    return decorator


def setup_rate_limiting(
    app: FastAPI,
    service_name: str,
    *,
    redis_url: str,
    key_func: Callable[[Request], str] | None = None,
    default_limits: list[str] | None = None,
) -> Storage:
    """Configure rate limiting for FastAPI application.

    Args:
        app: FastAPI application instance
        service_name: Service name for cache namespacing
        redis_url: URL of the Redis server
        key_func: Function to extract client identifier from request
        default_limits: Default rate limits to apply

    Returns:
        Configured Storage instance

    """
    if key_func is None:
        key_func = get_client_id

    if default_limits is None:
        default_limits = ["100/minute", "1000/hour"]

    storage = CacheUtilsStorage(service_name=service_name, redis_url=redis_url)

    app.add_middleware(RateLimitMiddleware, storage=storage, key_func=key_func, default_limits=default_limits)

    app.add_exception_handler(RateLimitExceededHTTP, rate_limit_exceeded_handler)

    return storage

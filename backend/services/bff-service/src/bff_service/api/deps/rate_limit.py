"""Per-route rate limit for the auth-listings endpoint.

Layers a fixed-key sliding-window bucket on top of the global rate-limit
middleware. The bucket key is constant because the only legitimate caller is
a single Cloudflare Worker sharing one secret; per-IP enforcement remains
with the global middleware. Raises 429 with a numeric ``Retry-After`` header
when the bucket is full.
"""

from __future__ import annotations

import math
from typing import Annotated, Final

from fastapi import Depends, HTTPException, status
from nohiki_redis_utils import CacheFactory, create_sliding_window_limiter

from bff_service.core.config import Settings, get_settings

# Used as the ``CacheFactory`` service name; it becomes the key prefix that
# isolates this bucket from other namespaces.
RATE_LIMIT_NAMESPACE: Final[str] = "rate-limit:auth-listings"

# Fixed (not per-IP): every Worker request shares one secret, so the bucket
# protects the route as a whole, not individual edge IPs.
RATE_LIMIT_KEY: Final[str] = "auth-listings"

RATE_LIMIT_WINDOW_SECONDS: Final[int] = 60

# The limiter can return retry_after=0 at the exact window boundary; floor it
# so the client always backs off for at least one second.
_RETRY_AFTER_MIN_SECONDS: Final[int] = 1


async def rate_limit_auth_listings(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Enforce the per-route rate limit for the auth-listings endpoint.

    Fail-open on Redis errors: ``SlidingWindowRateLimiter.check`` returns
    ``allowed=True`` when the cache is unreachable, matching the global
    middleware.

    Args:
        settings: Application settings. ``auth_listings.rate_limit_per_minute``
            sets the bucket capacity; ``redis.connection_string`` locates the
            backing Redis store.

    Raises:
        HTTPException: 429 Too Many Requests with a numeric ``Retry-After``
            header when the bucket is exhausted.
    """
    cache = CacheFactory.create_cache(
        RATE_LIMIT_NAMESPACE,
        redis_url=settings.redis.connection_string,
    )
    limiter = create_sliding_window_limiter(
        cache,
        requests=settings.auth_listings.rate_limit_per_minute,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )
    result = await limiter.check(RATE_LIMIT_KEY)
    if not result.allowed:
        retry_after_seconds = max(
            math.ceil(result.retry_after or 0),
            _RETRY_AFTER_MIN_SECONDS,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Auth-listings rate limit exceeded",
            headers={"Retry-After": str(retry_after_seconds)},
        )

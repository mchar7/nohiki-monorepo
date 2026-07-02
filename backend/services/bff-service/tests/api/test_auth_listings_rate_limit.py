"""Regression tests for the per-route auth-listings rate limit.

Covers three behaviors:

1. The first ``rate_limit_per_minute`` requests succeed.
2. The next request returns 429 with a numeric ``Retry-After``.
3. Secret validation short-circuits the limiter: a bad secret yields 403
   even when the bucket is empty, confirming dependency ordering.

A real Redis testcontainer is needed; ``SlidingWindowRateLimiter`` runs as
a Redis Lua script that no in-memory fake reproduces.

Uses ``httpx.AsyncClient`` with ``ASGITransport`` rather than
``fastapi.testclient.TestClient``. ``TestClient`` runs handlers in a worker
thread with its own anyio portal loop, so ``CacheFactory`` allocates two
cache instances (one per loop) and leaks the handler-side one at teardown.
The async client keeps fixture, test, and cleanup on one event loop.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from bff_service.api.deps.rate_limit import (
    RATE_LIMIT_KEY,
    RATE_LIMIT_NAMESPACE,
)
from bff_service.api.routers.auth_listings import router
from bff_service.core.config import AuthListingsSettings, Settings, get_settings
from bff_service.core.db import get_async_db
from fastapi import FastAPI
from httpx import ASGITransport
from nohiki_redis_utils import CacheFactory, RedisSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]

# Patched out because the rate-limit dep fires before this is invoked; the
# tests assert on HTTP semantics, not on listings content.
_COMPILE_PATH = "bff_service.api.routers.auth_listings.compile_auth_listings"

_TEST_SECRET = "rate-limit-test-secret"
_TEST_ROUTE = "/api/v1/auth-listings/"

# Production-default limit; the audit requires exercising the actual
# configured bound, not a synthetic low value.
_DEFAULT_RATE_LIMIT = 60

# Storage key produced by ``SlidingWindowRateLimiter`` (prefix defined in
# ``nohiki_redis_utils.rate_limiter``). The fixture deletes it per test.
_LIMITER_REDIS_KEY = f"ratelimit:sw:{RATE_LIMIT_KEY}"

HTTP_200 = 200
HTTP_403 = 403
HTTP_429 = 429


def _sample_response_dict() -> dict[str, object]:
    """Build a minimal auth-listings response payload for the mocked service."""
    return {
        "listings": [
            {
                "title": "Senior Python Engineer",
                "company_name": "Acme Corp",
                "location_raw": "San Francisco, CA",
                "work_arrangement": "REMOTE",
                "required_skills": ["Python", "FastAPI"],
                "posted_at": datetime.now(UTC).isoformat(),
                "language": "en",
            },
        ],
        "country": "USA",
    }


def _build_settings(redis_url: str, *, rate_limit: int = _DEFAULT_RATE_LIMIT) -> Settings:
    """Build Settings pointed at the testcontainer Redis.

    ``model_validate`` flows the raw URL string through a single Pydantic
    pass into a ``RedisDsn``. The cache clear pairs with the autouse reset
    in ``tests/conftest.py`` so a singleton mutated by a prior test cannot
    leak into this one.
    """
    get_settings.cache_clear()
    settings = get_settings()
    settings.redis = RedisSettings.model_validate({"dsn": redis_url})
    settings.auth_listings = AuthListingsSettings(
        secret=_TEST_SECRET,
        rate_limit_per_minute=rate_limit,
    )
    return settings


@contextlib.asynccontextmanager
async def _build_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an ``AsyncClient`` bound to a fresh app with overrides.

    The async transport keeps app, test, and ``CacheFactory`` cleanup on one
    event loop so Redis connections close cleanly.
    """
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/auth-listings")

    async def _override_db() -> AsyncMock:
        return AsyncMock()

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_async_db] = _override_db

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def _reset_rate_limit_state(redis_container: str) -> AsyncIterator[None]:
    """Reset the limiter key and ``CacheFactory`` singletons per test.

    ``redis_container`` is session-scoped, so without this hook one test
    would inherit the prior test's window state.
    """
    CacheFactory.clear_instances()
    cache = CacheFactory.create_cache(
        RATE_LIMIT_NAMESPACE,
        redis_url=redis_container,
    )
    await cache.delete(_LIMITER_REDIS_KEY)
    try:
        yield
    finally:
        await cache.delete(_LIMITER_REDIS_KEY)
        await CacheFactory.close_all()


@pytest.mark.usefixtures("_reset_rate_limit_state")
async def test_allows_up_to_limit_then_returns_429_with_retry_after(
    redis_container: str,
) -> None:
    """First ``rate_limit_per_minute`` requests succeed; overflow returns 429.

    Runs at the production-default 60/min so 61 requests prove the bound.
    The overflow response must carry a numeric ``Retry-After`` for the
    Worker to back off.
    """
    settings = _build_settings(redis_container, rate_limit=_DEFAULT_RATE_LIMIT)
    headers = {"X-Auth-Listings-Secret": _TEST_SECRET}
    params = {"country": "USA"}

    with patch(_COMPILE_PATH, new_callable=AsyncMock) as mock_compile:
        mock_compile.return_value = _sample_response_dict()
        async with _build_client(settings) as client:
            success_statuses = [
                (await client.get(_TEST_ROUTE, params=params, headers=headers)).status_code
                for _ in range(_DEFAULT_RATE_LIMIT)
            ]
            overflow = await client.get(_TEST_ROUTE, params=params, headers=headers)

    assert success_statuses == [HTTP_200] * _DEFAULT_RATE_LIMIT
    assert overflow.status_code == HTTP_429

    retry_after = overflow.headers.get("Retry-After")
    assert retry_after is not None, "429 response must include a Retry-After header"
    assert retry_after.isdigit(), f"Retry-After must be a non-negative integer, got {retry_after!r}"

    # The window is 60s and the bucket just filled, so Retry-After must be
    # at least 1 (back off) and at most 60 (next window roll-over).
    retry_after_seconds = int(retry_after)
    assert 1 <= retry_after_seconds <= 60


@pytest.mark.usefixtures("_reset_rate_limit_state")
async def test_invalid_secret_cannot_consume_worker_bucket(
    redis_container: str,
) -> None:
    """Rejected traffic leaves the entire authenticated Worker window available."""
    # Three calls instead of sixty so the exhaustion loop stays fast.
    tight_limit = 3
    settings = _build_settings(redis_container, rate_limit=tight_limit)
    valid_headers = {"X-Auth-Listings-Secret": _TEST_SECRET}
    bad_headers = {"X-Auth-Listings-Secret": "definitely-wrong-secret"}
    params = {"country": "USA"}

    with patch(_COMPILE_PATH, new_callable=AsyncMock) as mock_compile:
        mock_compile.return_value = _sample_response_dict()
        async with _build_client(settings) as client:
            rejected = [
                await client.get(_TEST_ROUTE, params=params, headers=bad_headers) for _ in range(tight_limit + 2)
            ]
            assert [response.status_code for response in rejected] == [HTTP_403] * (tight_limit + 2)

            for _ in range(tight_limit):
                inside = await client.get(_TEST_ROUTE, params=params, headers=valid_headers)
                assert inside.status_code == HTTP_200

            # All valid capacity remains after the rejected requests.
            exhausted = await client.get(_TEST_ROUTE, params=params, headers=valid_headers)
            assert exhausted.status_code == HTTP_429

            bad_secret = await client.get(_TEST_ROUTE, params=params, headers=bad_headers)

    assert bad_secret.status_code == HTTP_403
    assert "Retry-After" not in bad_secret.headers

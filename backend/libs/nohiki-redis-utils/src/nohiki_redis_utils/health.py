"""Cache health check utilities."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

import redis.asyncio as redis_async
from nohiki_common_exceptions import (
    HealthProbeResult,
    HealthProbeTimer,
    create_degraded_result,
    create_healthy_result,
    create_unhealthy_result,
)
from nohiki_observability import get_logger
from redis.asyncio import Redis, RedisError

from .redis_cache import RedisCache

logger = get_logger(__name__)


class HealthStatus(Enum):
    """Health check status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(slots=True)
class CacheHealthResult:
    """Health check result."""

    status: HealthStatus
    latency_ms: float
    message: str
    details: dict[str, object] | None = None


class RedisHealthProbe:
    """Health probe for Redis connectivity.

    Implements the HealthProbe protocol for Redis health checking.
    Supports both read-only (PING) and read-write (SET/GET/DELETE cycle) checks.
    """

    __slots__ = (
        "_client",
        "_degraded_threshold_ms",
        "_redis_url",
        "_require_write",
        "_timeout_ms",
    )

    def __init__(
        self,
        redis_url: str,
        *,
        timeout_ms: float = 1000.0,
        degraded_threshold_ms: float = 100.0,
        require_write: bool = True,
    ) -> None:
        """Initialize Redis health probe.

        Args:
            redis_url: Redis connection URL.
            timeout_ms: Maximum acceptable latency (UNHEALTHY if exceeded).
            degraded_threshold_ms: Latency threshold for DEGRADED status.
            require_write: If True, performs SET/GET/DELETE cycle; if False, PING only.

        """
        self._redis_url = redis_url
        self._timeout_ms = timeout_ms
        self._degraded_threshold_ms = degraded_threshold_ms
        self._require_write = require_write
        self._client: Redis[bytes] | None = None

    @property
    def name(self) -> str:
        """Probe identifier."""
        return "redis"

    def _get_client(self) -> Redis[bytes]:
        """Get or create Redis client."""
        if self._client is None:
            redis_from_url = cast("Any", redis_async.from_url)
            self._client = redis_from_url(
                self._redis_url,
                socket_connect_timeout=self._timeout_ms / 1000,
                socket_timeout=self._timeout_ms / 1000,
            )
        return self._client

    async def check(self) -> HealthProbeResult:
        """Execute Redis health check.

        If require_write=True: SET/GET/DELETE cycle.
        If require_write=False: PING only.
        """
        with HealthProbeTimer() as timer:
            try:
                client = self._get_client()

                if self._require_write:
                    result = await self._check_read_write(client)
                else:
                    result = await self._check_ping(client)

                if result is not None:
                    return result

            except RedisError as e:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Redis connection failed: {e}",
                    latency_ms=timer.elapsed_ms,
                    details={"error": str(e), "error_type": type(e).__name__},
                )

        return self._evaluate_latency(timer.elapsed_ms)

    async def _check_ping(self, client: Redis[bytes]) -> HealthProbeResult | None:
        """Execute PING check."""
        pong = await client.ping()
        if not pong:
            return create_unhealthy_result(
                name=self.name,
                message="Redis PING returned False",
                latency_ms=0.0,
            )
        return None

    async def _check_read_write(self, client: Redis[bytes]) -> HealthProbeResult | None:
        """Execute SET/GET/DELETE cycle."""
        test_key = "__health_probe__"
        test_value = f"probe_{time.time()}"

        await client.set(test_key, test_value, ex=60)
        read_value = await client.get(test_key)
        await client.delete(test_key)

        if read_value is None:
            return create_unhealthy_result(
                name=self.name,
                message="Redis read returned None after write",
                latency_ms=0.0,
            )

        decoded = read_value.decode() if isinstance(read_value, bytes) else read_value
        if decoded != test_value:
            return create_unhealthy_result(
                name=self.name,
                message="Redis read/write mismatch",
                latency_ms=0.0,
                details={"expected": test_value, "actual": decoded},
            )

        return None

    def _evaluate_latency(self, latency_ms: float) -> HealthProbeResult:
        """Evaluate latency and return appropriate result."""
        if latency_ms > self._timeout_ms:
            return create_unhealthy_result(
                name=self.name,
                message=f"Latency {latency_ms:.2f}ms exceeds timeout {self._timeout_ms:.2f}ms",
                latency_ms=latency_ms,
            )

        if latency_ms > self._degraded_threshold_ms:
            return create_degraded_result(
                name=self.name,
                message=f"Latency {latency_ms:.2f}ms exceeds degraded threshold {self._degraded_threshold_ms:.2f}ms",
                latency_ms=latency_ms,
            )

        return create_healthy_result(
            name=self.name,
            message="Redis is healthy",
            latency_ms=latency_ms,
        )

    async def close(self) -> None:
        """Close the Redis client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


async def ensure_redis_ready(
    redis_url: str,
    *,
    timeout_seconds: float = 30.0,
    retry_interval_seconds: float = 2.0,
) -> None:
    """Block startup until Redis is available.

    Args:
        redis_url: Redis connection URL.
        timeout_seconds: Maximum time to wait for Redis.
        retry_interval_seconds: Interval between retry attempts.

    Raises:
        RuntimeError: If Redis is unavailable after timeout.

    """
    probe = RedisHealthProbe(redis_url, require_write=False)
    start_time = time.perf_counter()
    attempt = 0

    logger.info(
        "Waiting for Redis to become available",
        timeout_seconds=timeout_seconds,
    )

    try:
        while (time.perf_counter() - start_time) < timeout_seconds:
            attempt += 1
            result = await probe.check()

            if result.is_healthy():
                elapsed = time.perf_counter() - start_time
                logger.info(
                    "Redis is available",
                    elapsed_seconds=round(elapsed, 2),
                    attempts=attempt,
                )
                return

            remaining = timeout_seconds - (time.perf_counter() - start_time)
            if remaining > 0:
                wait_time = min(retry_interval_seconds, remaining)
                logger.debug(
                    "Redis not available, retrying",
                    attempt=attempt,
                    error=result.message,
                    retry_in_seconds=wait_time,
                )
                await asyncio.sleep(wait_time)

        elapsed = time.perf_counter() - start_time
        msg = f"Redis unavailable after {elapsed:.1f}s ({attempt} attempts)"
        logger.error("Redis startup timeout", elapsed_seconds=round(elapsed, 2), attempts=attempt)
        raise RuntimeError(msg)

    finally:
        await probe.close()


async def check_cache_health(
    cache: RedisCache,
    timeout_ms: float = 1000.0,
    degraded_threshold_ms: float = 100.0,
) -> CacheHealthResult:
    """Perform cache health check with read/write/delete cycle.

    Args:
        cache: Cache instance to check
        timeout_ms: Maximum acceptable latency (UNHEALTHY if exceeded)
        degraded_threshold_ms: Latency threshold for DEGRADED status

    Returns:
        Health check result with status, latency, and message

    """
    test_key = "__health_check__"
    test_value = f"health_check_{time.time()}"

    start = time.perf_counter()

    try:
        # Write test value
        await cache.set(test_key, test_value, ttl=60)

        # Read back and verify
        read_value = await cache.get(test_key)

        # Delete test key
        await cache.delete(test_key)

        latency_ms = (time.perf_counter() - start) * 1000

        # Verify read value matches written value
        if read_value != test_value:
            logger.warning(
                "Health check read miscorrelation",
                expected=test_value,
                actual=read_value,
                latency_ms=round(latency_ms, 2),
            )
            return CacheHealthResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                message="Read value does not correlation written value",
                details={"expected": test_value, "actual": read_value},
            )

        # Determine status based on latency
        if latency_ms > timeout_ms:
            logger.warning(
                "Health check timeout exceeded",
                latency_ms=round(latency_ms, 2),
                timeout_ms=timeout_ms,
            )
            return CacheHealthResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                message=f"Latency {latency_ms:.2f}ms exceeds timeout {timeout_ms:.2f}ms",
            )

        if latency_ms > degraded_threshold_ms:
            logger.info(
                "Health check degraded",
                latency_ms=round(latency_ms, 2),
                threshold_ms=degraded_threshold_ms,
            )
            return CacheHealthResult(
                status=HealthStatus.DEGRADED,
                latency_ms=latency_ms,
                message=f"Latency {latency_ms:.2f}ms exceeds degraded threshold {degraded_threshold_ms:.2f}ms",
            )

        logger.debug(
            "Health check passed",
            latency_ms=round(latency_ms, 2),
        )
        return CacheHealthResult(
            status=HealthStatus.HEALTHY,
            latency_ms=latency_ms,
            message="Cache is healthy",
        )

    except RedisError as e:
        latency_ms = (time.perf_counter() - start) * 1000
        logger.warning(
            "Health check failed",
            error=str(e),
            error_type=type(e).__name__,
            latency_ms=round(latency_ms, 2),
        )
        return CacheHealthResult(
            status=HealthStatus.UNHEALTHY,
            latency_ms=latency_ms,
            message=f"Health check failed: {e}",
            details={"error": str(e), "error_type": type(e).__name__},
        )

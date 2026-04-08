"""Testing utilities for Redis cache - testcontainer fixtures and helpers."""

from __future__ import annotations

import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

import pytest
import redis.asyncio as redis
from nohiki_test_utils import docker_daemon_available

from nohiki_redis_utils.redis_cache import RedisCache

VALKEY_CONTAINER_IMAGE = "valkey/valkey:9-alpine"
VALKEY_PORT = 6379
REDIS_PORT = 6379


@pytest.fixture(scope="session")
def redis_container() -> Generator[str]:
    """Create and manage Redis test container.

    Uses ``DockerContainer`` directly instead of ``RedisContainer`` to avoid
    the deprecated ``@wait_container_is_ready`` decorator that testcontainers
    4.x still applies to ``RedisContainer`` at class definition time.

    Returns:
        Redis connection URL (redis://host:port)

    Raises:
        pytest.skip: If Docker daemon is unavailable

    """
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import ExecWaitStrategy

    container: DockerContainer | None = None
    try:
        if not docker_daemon_available():
            pytest.skip("Redis container could not be started: Docker daemon unavailable")

        container = DockerContainer(VALKEY_CONTAINER_IMAGE)
        container.with_exposed_ports(VALKEY_PORT)
        container.waiting_for(ExecWaitStrategy(["valkey-cli", "ping"]).with_startup_timeout(timedelta(seconds=30)))
        container.start()

        host = container.get_container_host_ip()
        port = container.get_exposed_port(VALKEY_PORT)
        yield f"redis://{host}:{port}"

    except (RuntimeError, OSError) as e:
        pytest.skip(f"Redis container could not be started: {e}")
    finally:
        if container is not None:
            with contextlib.suppress(Exception):
                container.stop()


@pytest.fixture
async def redis_client(redis_container: str) -> AsyncGenerator[redis.Redis[bytes]]:
    """Create Redis client using the test container.

    Args:
        redis_container: Redis connection URL from redis_container fixture

    Yields:
        Async Redis client instance

    """
    client: redis.Redis[bytes] = redis.from_url(redis_container)

    yield client

    await client.aclose()


@pytest.fixture
async def redis_cache(redis_container: str) -> AsyncGenerator[RedisCache]:
    """Create RedisCache instance using the test container.

    Args:
        redis_container: Redis connection URL from redis_container fixture

    Yields:
        RedisCache instance configured for testing

    """
    cache = RedisCache(redis_url=redis_container, service_name="test")

    yield cache

    await cache.close()

"""Tests for nohiki-redis-utils testing fixtures with mocked Docker.

Exercises the fixture code paths (container creation, client/cache
yield, cleanup) without requiring an actual Docker daemon.  Accesses the
raw generator via ``__wrapped__`` to bypass pytest's fixture machinery.
"""

from __future__ import annotations

import contextlib
import inspect
from collections.abc import AsyncGenerator, Callable, Generator
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis
from nohiki_redis_utils.redis_cache import RedisCache
from nohiki_redis_utils.testing import (
    VALKEY_CONTAINER_IMAGE,
    VALKEY_PORT,
    redis_cache,
    redis_client,
    redis_container,
)

# Access the raw generator functions behind the fixture decorators.
_raw_redis_container = cast("Callable[[], Generator[str]]", inspect.unwrap(redis_container))
_raw_redis_client = cast("Callable[[str], AsyncGenerator[redis.Redis]]", inspect.unwrap(redis_client))
_raw_redis_cache = cast("Callable[[str], AsyncGenerator[RedisCache]]", inspect.unwrap(redis_cache))


class TestRedisContainerFixtureMocked:
    """Tests for redis_container fixture with mocked Docker."""

    def test_yields_connection_url_when_docker_available(self) -> None:
        """Fixture yields redis:// URL when Docker is available."""
        mock_container = MagicMock()
        mock_container.get_container_host_ip.return_value = "127.0.0.1"
        mock_container.get_exposed_port.return_value = 12345

        with (
            patch("nohiki_redis_utils.testing.docker_daemon_available", return_value=True),
            patch(
                "testcontainers.core.container.DockerContainer",
                return_value=mock_container,
            ) as mock_cls,
        ):
            gen = _raw_redis_container()
            url = next(gen)

            assert url == "redis://127.0.0.1:12345"
            mock_cls.assert_called_once_with(VALKEY_CONTAINER_IMAGE)
            mock_container.with_exposed_ports.assert_called_once_with(VALKEY_PORT)
            mock_container.start.assert_called_once()

            # Cleanup
            with contextlib.suppress(StopIteration):
                next(gen)
            mock_container.stop.assert_called_once()

    def test_skips_when_docker_unavailable(self) -> None:
        """Fixture calls pytest.skip when Docker daemon is unavailable."""
        with patch("nohiki_redis_utils.testing.docker_daemon_available", return_value=False):
            gen = _raw_redis_container()
            with pytest.raises(pytest.skip.Exception):
                next(gen)

    def test_skips_on_runtime_error(self) -> None:
        """Fixture calls pytest.skip on RuntimeError during container start."""
        mock_container = MagicMock()
        mock_container.start.side_effect = RuntimeError("Docker not running")

        with (
            patch("nohiki_redis_utils.testing.docker_daemon_available", return_value=True),
            patch(
                "testcontainers.core.container.DockerContainer",
                return_value=mock_container,
            ),
        ):
            gen = _raw_redis_container()
            with pytest.raises(pytest.skip.Exception, match="Docker not running"):
                next(gen)


class TestRedisClientFixtureMocked:
    """Tests for redis_client fixture with mocked Redis."""

    @pytest.mark.asyncio
    async def test_yields_redis_client_and_closes(self) -> None:
        """Fixture yields a Redis client and closes it on teardown."""
        mock_client = AsyncMock()

        with patch("nohiki_redis_utils.testing.redis.from_url", return_value=mock_client):
            gen = _raw_redis_client("redis://localhost:6379")
            client = await gen.__anext__()

            assert client is mock_client

            # Teardown
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
            mock_client.aclose.assert_awaited_once()


class TestRedisCacheFixtureMocked:
    """Tests for redis_cache fixture with mocked RedisCache."""

    @pytest.mark.asyncio
    async def test_yields_cache_and_closes(self) -> None:
        """Fixture yields a RedisCache instance and closes it on teardown."""
        mock_cache = AsyncMock()

        with patch("nohiki_redis_utils.testing.RedisCache", return_value=mock_cache):
            gen = _raw_redis_cache("redis://localhost:6379")
            cache = await gen.__anext__()

            assert cache is mock_cache

            # Teardown
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
            mock_cache.close.assert_awaited_once()

"""Pytest fixtures for nohiki-redis-utils tests."""

from __future__ import annotations

import asyncio
import contextlib
import warnings
from collections.abc import Generator

import pytest
from nohiki_redis_utils.testing import redis_cache, redis_client, redis_container

__all__ = ["redis_cache", "redis_client", "redis_container"]


@pytest.fixture(autouse=True)
def _close_stale_event_loops() -> Generator[None]:
    """Close any event loop left in thread-local state between tests.

    pytest-asyncio sets a new event loop in the thread-local policy but
    does not always close it before the next test starts. If a subsequent
    sync test calls ``asyncio.run()``, the orphaned loop is silently
    dropped and its self-pipe sockets leak, triggering
    ``ResourceWarning: unclosed event loop``.
    """
    yield
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
    if not loop.is_closed():
        loop.close()
    asyncio.set_event_loop(None)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Close testcontainers Reaper socket after test session ends."""
    _ = (session, exitstatus)
    with contextlib.suppress(Exception):
        from testcontainers.core.container import Reaper

        Reaper.delete_instance()

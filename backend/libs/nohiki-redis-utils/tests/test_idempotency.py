"""Tests for Redis-based idempotency."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from nohiki_redis_utils.idempotency import check_and_mark_processed_redis


class TestCheckAndMarkProcessedRedis:
    """Tests for check_and_mark_processed_redis function."""

    @pytest.mark.asyncio
    async def test_new_event_returns_true(self) -> None:
        """New event (SETNX succeeds) returns True."""
        mock_cache = AsyncMock()
        mock_cache.setnx_strict.return_value = True

        result = await check_and_mark_processed_redis(
            cache=mock_cache,
            event_id="evt-123",
            handler_name="handle_something",
        )

        assert result is True
        mock_cache.setnx_strict.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_event_returns_false(self) -> None:
        """Duplicate event (SETNX fails) returns False."""
        mock_cache = AsyncMock()
        mock_cache.setnx_strict.return_value = False

        result = await check_and_mark_processed_redis(
            cache=mock_cache,
            event_id="evt-123",
            handler_name="handle_something",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_custom_ttl(self) -> None:
        """Custom TTL is passed to setnx."""
        mock_cache = AsyncMock()
        mock_cache.setnx_strict.return_value = True

        await check_and_mark_processed_redis(
            cache=mock_cache,
            event_id="evt-456",
            handler_name="handle_job",
            ttl_seconds=3600,
        )

        mock_cache.setnx_strict.assert_called_once_with("processed:handle_job:evt-456", "1", ttl=3600)

    @pytest.mark.asyncio
    async def test_key_format(self) -> None:
        """Key format is processed:{handler_name}:{event_id}."""
        mock_cache = AsyncMock()
        mock_cache.setnx_strict.return_value = True

        await check_and_mark_processed_redis(
            cache=mock_cache,
            event_id="abc-def-ghi",
            handler_name="my_handler",
        )

        call_args = mock_cache.setnx_strict.call_args
        assert call_args[0][0] == "processed:my_handler:abc-def-ghi"

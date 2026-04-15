"""Tests for the deduplication service.

The dedup service uses Redis for content-hash based deduplication of job listings.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_discovery_service.services.dedup_service import (
    _DEDUP_PREFIX,
    DedupService,
    get_dedup_service,
)


class TestDedupService:
    """Tests for DedupService class."""

    @pytest.fixture
    def mock_cache(self) -> MagicMock:
        """Create a mock cache."""
        cache = MagicMock()
        cache.exists = AsyncMock(return_value=False)
        cache.set = AsyncMock()
        return cache

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.service_name = "job-ingest-discovery-service"
        settings.redis.connection_string = "redis://localhost:6379"
        settings.caching.dedup_ttl_seconds = 2592000  # 30 days
        return settings

    def test_init(self, mock_cache: MagicMock, mock_settings: MagicMock) -> None:
        """Test DedupService initialization."""
        with (
            patch(
                "job_ingest_discovery_service.services.dedup_service.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "job_ingest_discovery_service.services.dedup_service._get_cache",
                return_value=mock_cache,
            ),
        ):
            service = DedupService()
            assert service._ttl == 2592000

    @pytest.mark.asyncio
    async def test_is_duplicate_false(self, mock_cache: MagicMock, mock_settings: MagicMock) -> None:
        """Test is_duplicate returns False when hash not seen."""
        mock_cache.exists = AsyncMock(return_value=False)

        with (
            patch(
                "job_ingest_discovery_service.services.dedup_service.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "job_ingest_discovery_service.services.dedup_service._get_cache",
                return_value=mock_cache,
            ),
        ):
            service = DedupService()
            result = await service.is_duplicate("abc123def456")

            assert result is False
            mock_cache.exists.assert_awaited_once_with(f"{_DEDUP_PREFIX}:hash:abc123def456")

    @pytest.mark.asyncio
    async def test_is_duplicate_true(self, mock_cache: MagicMock, mock_settings: MagicMock) -> None:
        """Test is_duplicate returns True when hash was seen."""
        mock_cache.exists = AsyncMock(return_value=True)

        with (
            patch(
                "job_ingest_discovery_service.services.dedup_service.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "job_ingest_discovery_service.services.dedup_service._get_cache",
                return_value=mock_cache,
            ),
        ):
            service = DedupService()
            result = await service.is_duplicate("abc123def456")

            assert result is True

    @pytest.mark.asyncio
    async def test_mark_seen(self, mock_cache: MagicMock, mock_settings: MagicMock) -> None:
        """Test mark_seen sets the hash in cache with TTL."""
        with (
            patch(
                "job_ingest_discovery_service.services.dedup_service.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "job_ingest_discovery_service.services.dedup_service._get_cache",
                return_value=mock_cache,
            ),
        ):
            service = DedupService()
            await service.mark_seen("abc123def456")

            mock_cache.set.assert_awaited_once_with(
                f"{_DEDUP_PREFIX}:hash:abc123def456",
                "1",
                ttl=2592000,
            )


class TestGetDedupService:
    """Tests for get_dedup_service singleton function."""

    def test_returns_singleton(self) -> None:
        """Test that get_dedup_service returns singleton instance."""
        mock_cache = MagicMock()
        mock_cache.exists = AsyncMock()
        mock_cache.set = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.service_name = "job-ingest-discovery-service"
        mock_settings.redis.connection_string = "redis://localhost:6379"
        mock_settings.caching.dedup_ttl_seconds = 2592000

        with (
            patch(
                "job_ingest_discovery_service.services.dedup_service.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "job_ingest_discovery_service.services.dedup_service._get_cache",
                return_value=mock_cache,
            ),
            patch(
                "job_ingest_discovery_service.services.dedup_service._DedupServiceHolder.instance",
                None,
            ),
        ):
            service1 = get_dedup_service()
            service2 = get_dedup_service()

            # Both calls should return the same instance (singleton)
            assert service1 is service2


class TestDedupPrefix:
    """Tests for dedup key prefix constant."""

    def test_prefix_value(self) -> None:
        """Test that the dedup prefix is correct."""
        assert _DEDUP_PREFIX == "dedup"

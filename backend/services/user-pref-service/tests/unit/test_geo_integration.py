"""Unit tests for geo_integration module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.common.v1 import CountryCode, Location
from user_pref_service.services.geo_integration import (
    _get_cached_geocoder,
    geocode_locations,
)


@pytest.fixture(autouse=True)
def _reset_geocoder_cache() -> None:
    """Reset @cache on _get_cached_geocoder before each test."""
    _get_cached_geocoder.cache_clear()


class TestGetCachedGeocoder:
    """Tests for _get_cached_geocoder function."""

    @patch("user_pref_service.services.geo_integration.create_cached_geocoder")
    @patch("user_pref_service.services.geo_integration.get_settings")
    def test_creates_cached_geocoder_on_first_call(
        self, mock_get_settings: MagicMock, mock_create_geocoder: MagicMock
    ) -> None:
        """Creates cached geocoder on first call."""
        mock_settings = MagicMock()
        mock_settings.service_name = "user-pref-service"
        mock_settings.redis.connection_string = "redis://localhost:6379/0"
        mock_get_settings.return_value = mock_settings

        mock_geocoder = AsyncMock()
        mock_create_geocoder.return_value = (MagicMock(), mock_geocoder)

        result = _get_cached_geocoder()

        assert result is mock_geocoder
        mock_create_geocoder.assert_called_once()

    @patch("user_pref_service.services.geo_integration.create_cached_geocoder")
    @patch("user_pref_service.services.geo_integration.get_settings")
    def test_returns_cached_geocoder_on_subsequent_calls(
        self, mock_get_settings: MagicMock, mock_create_geocoder: MagicMock
    ) -> None:
        """Returns same geocoder on subsequent calls via @cache."""
        mock_settings = MagicMock()
        mock_settings.service_name = "user-pref-service"
        mock_settings.redis.connection_string = "redis://localhost:6379/0"
        mock_get_settings.return_value = mock_settings

        mock_geocoder = AsyncMock()
        mock_create_geocoder.return_value = (MagicMock(), mock_geocoder)

        result1 = _get_cached_geocoder()
        result2 = _get_cached_geocoder()

        assert result1 is result2
        assert mock_create_geocoder.call_count == 1


class TestGeocodeLocations:
    """Tests for geocode_locations function."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_empty_input(self) -> None:
        """Returns empty list for empty input."""
        result = await geocode_locations([])
        assert result == []

    @pytest.mark.asyncio
    @patch("user_pref_service.services.geo_integration._get_cached_geocoder")
    async def test_geocodes_single_location_directly(self, mock_get_geocoder: MagicMock) -> None:
        """Geocodes a single location with direct await (no TaskGroup)."""
        mock_geocoder = AsyncMock()
        mock_geocoder.return_value = Location(city="Toronto", country=CountryCode.CAN)
        mock_get_geocoder.return_value = mock_geocoder

        locations = [Location(city="Toronto", country=CountryCode.CAN)]
        result = await geocode_locations(locations)

        assert len(result) == 1
        assert result[0].city == "Toronto"
        mock_geocoder.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("user_pref_service.services.geo_integration._get_cached_geocoder")
    async def test_geocodes_multiple_locations_via_taskgroup(self, mock_get_geocoder: MagicMock) -> None:
        """Geocodes multiple locations concurrently via TaskGroup."""
        mock_geocoder = AsyncMock()
        mock_geocoder.side_effect = [
            Location(city="Toronto", country=CountryCode.CAN),
            Location(city="Vancouver", country=CountryCode.CAN),
        ]
        mock_get_geocoder.return_value = mock_geocoder

        locations = [
            Location(city="Toronto", country=CountryCode.CAN),
            Location(city="Vancouver", country=CountryCode.CAN),
        ]

        result = await geocode_locations(locations)

        assert len(result) == 2
        assert result[0].city == "Toronto"
        assert result[1].city == "Vancouver"
        assert mock_geocoder.call_count == 2

    @pytest.mark.asyncio
    @patch("user_pref_service.services.geo_integration._get_cached_geocoder")
    async def test_keeps_original_location_on_geocoding_failure(self, mock_get_geocoder: MagicMock) -> None:
        """Keeps original location when geocoding fails."""
        mock_geocoder = AsyncMock()
        mock_geocoder.side_effect = OSError("Network error")
        mock_get_geocoder.return_value = mock_geocoder

        original_location = Location(city="Toronto", country=CountryCode.CAN)
        result = await geocode_locations([original_location])

        assert len(result) == 1
        assert result[0] is original_location

    @pytest.mark.asyncio
    @patch("user_pref_service.services.geo_integration._get_cached_geocoder")
    async def test_handles_value_error_during_geocoding(self, mock_get_geocoder: MagicMock) -> None:
        """Handles ValueError during geocoding gracefully."""
        mock_geocoder = AsyncMock()
        mock_geocoder.side_effect = ValueError("Invalid location")
        mock_get_geocoder.return_value = mock_geocoder

        original_location = Location(city="InvalidCity")
        result = await geocode_locations([original_location])

        assert len(result) == 1
        assert result[0] is original_location

    @pytest.mark.asyncio
    @patch("user_pref_service.services.geo_integration._get_cached_geocoder")
    async def test_handles_generic_exception_during_geocoding(self, mock_get_geocoder: MagicMock) -> None:
        """Handles generic Exception during geocoding (e.g. Redis errors)."""
        mock_geocoder = AsyncMock()
        mock_geocoder.side_effect = RuntimeError("Redis connection refused")
        mock_get_geocoder.return_value = mock_geocoder

        original_location = Location(city="Toronto", country=CountryCode.CAN)
        result = await geocode_locations([original_location])

        assert len(result) == 1
        assert result[0] is original_location

    @pytest.mark.asyncio
    @patch("user_pref_service.services.geo_integration._get_cached_geocoder")
    async def test_continues_geocoding_after_failure(self, mock_get_geocoder: MagicMock) -> None:
        """Continues geocoding after one location fails."""
        mock_geocoder = AsyncMock()
        mock_geocoder.side_effect = [
            OSError("Network error"),
            Location(city="Vancouver", country=CountryCode.CAN),
        ]
        mock_get_geocoder.return_value = mock_geocoder

        locations = [
            Location(city="Toronto", country=CountryCode.CAN),
            Location(city="Vancouver", country=CountryCode.CAN),
        ]

        result = await geocode_locations(locations)

        assert len(result) == 2
        assert result[0].city == "Toronto"
        assert result[1].city == "Vancouver"

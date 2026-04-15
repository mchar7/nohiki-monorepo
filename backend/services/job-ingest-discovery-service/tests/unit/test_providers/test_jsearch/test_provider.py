from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_discovery_service.core.models import DiscoveryRequest, RawListing
from job_ingest_discovery_service.providers.jsearch.exceptions import (
    JSearchNotConfiguredError,
    JSearchRateLimitError,
)
from job_ingest_discovery_service.providers.jsearch.models import JSearchResponse
from job_ingest_discovery_service.providers.jsearch.provider import JSearchProvider
from nohiki.common.v1 import JobBoardSource


def _mock_client(**attrs: object) -> MagicMock:
    """Create a MagicMock with the given attributes set."""
    mock = MagicMock()
    for key, value in attrs.items():
        setattr(mock, key, value)
    return mock


@pytest.mark.asyncio
async def test_health_check_reflects_client_configuration() -> None:
    provider = JSearchProvider(client=_mock_client(is_configured=True))

    assert await provider.health_check() is True


@pytest.mark.asyncio
async def test_discover_returns_error_when_not_configured() -> None:
    client = _mock_client(
        is_configured=False,
        search=AsyncMock(side_effect=JSearchNotConfiguredError()),
    )
    provider = JSearchProvider(client=client)

    request = DiscoveryRequest(
        query_id="q1",
        keywords=("python",),
        sources=(JobBoardSource.GOOGLE,),
        locations=(),
        work_arrangements=(),
    )

    result = await provider.discover(request)

    assert result.listings == []
    assert result.error == "JSearch provider not configured"


@pytest.mark.asyncio
async def test_discover_sets_error_code_and_retry_after_on_rate_limit() -> None:
    client = _mock_client(
        is_configured=True,
        search=AsyncMock(side_effect=JSearchRateLimitError(tier_name="hourly", retry_after_seconds=456.0)),
    )
    provider = JSearchProvider(client=client)

    request = DiscoveryRequest(
        query_id="q1",
        keywords=("python",),
        sources=(JobBoardSource.GOOGLE,),
        locations=(),
        work_arrangements=(),
    )

    result = await provider.discover(request)

    assert result.listings == []
    assert result.error_code == "rate_limited"
    assert result.retry_after_seconds == pytest.approx(456.0)
    assert result.error is not None
    assert "Hourly quota exhausted" in result.error


@pytest.mark.asyncio
async def test_discover_handles_unexpected_error() -> None:
    client = _mock_client(
        is_configured=True,
        search=AsyncMock(side_effect=RuntimeError("boom")),
    )
    provider = JSearchProvider(client=client)

    request = DiscoveryRequest(
        query_id="q1",
        keywords=("python",),
        sources=(JobBoardSource.GOOGLE,),
        locations=(),
        work_arrangements=(),
    )

    result = await provider.discover(request)

    assert result.listings == []
    assert result.error == "boom"


@pytest.mark.asyncio
async def test_discover_success_deduplicates_listings_across_searches() -> None:
    response = JSearchResponse(status="OK", data=[])
    client = _mock_client(
        is_configured=True,
        search=AsyncMock(return_value=response),
    )
    provider = JSearchProvider(client=client)

    request = DiscoveryRequest(
        query_id="q1",
        keywords=("python", "python2"),
        sources=(JobBoardSource.GOOGLE,),
        results_per_source=20,
        locations=(),
        work_arrangements=(),
    )

    listings_1 = [
        RawListing(
            listing_url="u1", title="t", company="c", source=JobBoardSource.GOOGLE, external_id="1", description="d"
        ),
        RawListing(
            listing_url="u2", title="t", company="c", source=JobBoardSource.GOOGLE, external_id="2", description="d"
        ),
    ]
    listings_2 = [
        RawListing(
            listing_url="u2", title="t", company="c", source=JobBoardSource.GOOGLE, external_id="2", description="d"
        ),
        RawListing(
            listing_url="u3", title="t", company="c", source=JobBoardSource.GOOGLE, external_id="3", description="d"
        ),
    ]

    with patch(
        "job_ingest_discovery_service.providers.jsearch.provider.map_response_to_listings",
        side_effect=[listings_1, listings_2],
    ):
        result = await provider.discover(request)

    assert result.error is None
    assert len(result.listings) == 3
    assert client.search.await_count == 2

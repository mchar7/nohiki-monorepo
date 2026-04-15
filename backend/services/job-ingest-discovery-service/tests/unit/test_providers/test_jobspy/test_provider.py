from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from job_ingest_discovery_service.core.models import DiscoveryRequest, RawListing
from job_ingest_discovery_service.providers.jobspy.provider import JobSpyProvider
from nohiki.common.v1 import JobBoardSource


@pytest.mark.asyncio
async def test_discover_returns_empty_when_no_params() -> None:
    provider = JobSpyProvider()
    request = DiscoveryRequest(
        query_id="q1",
        keywords=("python",),
        sources=(JobBoardSource.INDEED,),
        locations=(),
        work_arrangements=(),
    )

    with patch(
        "job_ingest_discovery_service.providers.jobspy.provider.build_jobspy_params",
        return_value=[],
    ):
        result = await provider.discover(request)

    assert result.error is None
    assert result.listings == []


@pytest.mark.asyncio
async def test_discover_success_deduplicates_results() -> None:
    provider = JobSpyProvider()
    request = DiscoveryRequest(
        query_id="q1",
        keywords=("python",),
        sources=(JobBoardSource.INDEED,),
        locations=(),
        work_arrangements=(),
    )

    df = pd.DataFrame([{"listing_url": "https://example.com/1"}])

    listings = [
        RawListing(listing_url="u1", title="t", company="c", source=JobBoardSource.INDEED, description="d"),
        RawListing(listing_url="u1", title="t2", company="c", source=JobBoardSource.INDEED, description="d"),
        RawListing(listing_url="u2", title="t3", company="c", source=JobBoardSource.INDEED, description="d"),
    ]

    with (
        patch(
            "job_ingest_discovery_service.providers.jobspy.provider.build_jobspy_params",
            return_value=[{"site_name": ["indeed"], "search_term": "python", "results_wanted": 10}],
        ),
        patch(
            "job_ingest_discovery_service.providers.jobspy.provider.map_dataframe_to_listings",
            return_value=listings,
        ),
        patch.object(provider, "_fetch_all", new=AsyncMock(return_value=[df])),
    ):
        result = await provider.discover(request)

    assert result.error is None
    assert len(result.listings) == 2
    assert result.listings[0].listing_url == "u1"
    assert result.listings[1].listing_url == "u2"


@pytest.mark.asyncio
async def test_fetch_all_filters_exceptions_and_empty_frames() -> None:
    provider = JobSpyProvider()

    empty_df = pd.DataFrame([])
    ok_df = pd.DataFrame([{"listing_url": "https://example.com/1"}])

    object.__setattr__(provider, "_fetch_one", MagicMock(side_effect=[empty_df, ValueError("boom"), ok_df]))

    async def _to_thread(func: Callable[..., object], *args: object, **kwargs: object) -> object:
        await asyncio.sleep(0)
        return func(*args, **kwargs)

    with patch(
        "job_ingest_discovery_service.providers.jobspy.provider.asyncio.to_thread",
        side_effect=_to_thread,
    ):
        dataframes = await provider._fetch_all(
            query_id="q1",
            param_sets=[{"a": 1}, {"b": 2}, {"c": 3}],
        )

    assert len(dataframes) == 1
    assert dataframes[0].equals(ok_df)


def test_fetch_one_captures_output_and_returns_df() -> None:
    provider = JobSpyProvider()
    df = pd.DataFrame([{"listing_url": "https://example.com/1"}])

    def _scrape_jobs(**_kwargs: object) -> pd.DataFrame:
        sys.stdout.write("jobspy output\n")
        return df

    with (
        patch(
            "job_ingest_discovery_service.providers.jobspy.provider.jobspy.scrape_jobs",
            side_effect=_scrape_jobs,
        ),
        patch("job_ingest_discovery_service.providers.jobspy.provider.logger") as mock_logger,
    ):
        result = provider._fetch_one("q1", {"site_name": ["indeed"], "search_term": "python"})

    assert result is not None
    assert result.equals(df)
    mock_logger.debug.assert_called_once()

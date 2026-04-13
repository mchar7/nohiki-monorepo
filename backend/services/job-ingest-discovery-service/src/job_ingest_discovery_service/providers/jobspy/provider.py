"""JobSpy provider: discovers jobs via the jobspy library."""

from __future__ import annotations

import asyncio
import contextlib
import io
import time

import jobspy
import pandas as pd
from nohiki.common.v1 import JobBoardSource
from nohiki_observability import get_logger

from job_ingest_discovery_service.core.config import get_settings
from job_ingest_discovery_service.core.models import DiscoveryRequest, DiscoveryResult, RawListing
from job_ingest_discovery_service.providers.base import BaseProvider, get_leaf_fetch_limiter
from job_ingest_discovery_service.providers.jobspy.mapper import (
    JobSpyParams,
    build_jobspy_params,
    map_dataframe_to_listings,
)
from job_ingest_discovery_service.providers.metrics import (
    DiscoveryMetricData,
    DiscoveryProviderMetrics,
    get_discovery_provider_metrics,
)

logger = get_logger(__name__)


class JobSpyProvider(BaseProvider):
    """Provider using the jobspy library for Indeed, LinkedIn, Glassdoor."""

    @property
    def name(self) -> str:
        """Provider identifier."""
        return "jobspy"

    @property
    def supported_sources(self) -> list[JobBoardSource]:
        """Supported job board sources."""
        return [JobBoardSource.INDEED, JobBoardSource.LINKEDIN, JobBoardSource.GLASSDOOR]

    def default_enabled(self) -> bool:
        """Return True as JobSpy is enabled by default."""
        return True

    def default_priority(self) -> int:
        """Return default priority (lower = higher priority)."""
        return 50

    async def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        """Execute job discovery using jobspy."""
        metrics = get_discovery_provider_metrics()
        start = time.monotonic()
        source_name = request.sources[0].name.lower() if request.sources else "unknown"

        logger.info(
            "Starting discovery", provider=self.name, query_id=request.query_id, keywords=list(request.keywords)
        )

        try:
            param_sets = build_jobspy_params(request)
            if not param_sets:
                return self._empty_result(start, metrics, source_name)

            dataframes = await self._fetch_all(request.query_id, param_sets)
            listings = self._combine_and_dedupe(dataframes)

            duration = time.monotonic() - start
            self._record_success(metrics, source_name, duration, len(listings))
            logger.info("Discovery completed", provider=self.name, query_id=request.query_id, count=len(listings))

            return DiscoveryResult(listings=listings, provider_name=self.name, duration_seconds=duration)

        except Exception as e:
            duration = time.monotonic() - start
            self._record_failure(metrics, source_name, duration, type(e).__name__)
            logger.exception("Discovery failed", provider=self.name, query_id=request.query_id)
            return DiscoveryResult(listings=[], provider_name=self.name, duration_seconds=duration, error=str(e))

    def _empty_result(self, start: float, metrics: DiscoveryProviderMetrics, source: str) -> DiscoveryResult:
        duration = time.monotonic() - start
        self._record_success(metrics, source, duration, 0)
        return DiscoveryResult(listings=[], provider_name=self.name, duration_seconds=duration)

    async def _fetch_all(self, query_id: str, param_sets: list[JobSpyParams]) -> list[pd.DataFrame]:
        """Fetch parameter sets concurrently under the command-wide leaf limit."""
        semaphore = get_leaf_fetch_limiter() or asyncio.Semaphore(get_settings().discovery.max_concurrent)

        async def _safe_fetch(idx: int, params: JobSpyParams) -> pd.DataFrame | None:
            try:
                async with semaphore:
                    fetch_task = asyncio.create_task(asyncio.to_thread(self._fetch_one, query_id, params))
                    try:
                        df = await asyncio.shield(fetch_task)
                    except asyncio.CancelledError:
                        await fetch_task
                        raise
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df.dropna(axis=1, how="all")
            except Exception as exc:  # noqa: BLE001 - jobspy raises unpredictable exceptions during web scraping
                logger.warning("Fetch failed", query_id=query_id, param_set=idx, error=str(exc))
            return None

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_safe_fetch(i, p)) for i, p in enumerate(param_sets)]

        return [r for t in tasks if (r := t.result()) is not None]

    def _fetch_one(self, query_id: str, params: JobSpyParams) -> pd.DataFrame | None:
        """Execute single jobspy fetch, capturing stdout/stderr."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            df: pd.DataFrame | None = jobspy.scrape_jobs(**params)
        if out := buf.getvalue():
            logger.debug("JobSpy output", query_id=query_id, output=out[:500])
        return df

    def _combine_and_dedupe(self, dfs: list[pd.DataFrame]) -> list[RawListing]:
        """Combine DataFrames and deduplicate by URL."""
        if not dfs:
            return []
        combined = pd.concat(dfs, ignore_index=True)
        listings = map_dataframe_to_listings(combined)

        seen: set[str] = set()
        unique: list[RawListing] = []
        for listing in listings:
            if listing.listing_url not in seen:
                seen.add(listing.listing_url)
                unique.append(listing)
        return unique

    def _record_success(self, metrics: DiscoveryProviderMetrics, source: str, duration: float, count: int) -> None:
        metrics.record_discovery(
            DiscoveryMetricData(
                provider=self.name, source=source, duration_seconds=duration, listings_found=count, success=True
            )
        )

    def _record_failure(self, metrics: DiscoveryProviderMetrics, source: str, duration: float, error_type: str) -> None:
        metrics.record_discovery(
            DiscoveryMetricData(
                provider=self.name,
                source=source,
                duration_seconds=duration,
                listings_found=0,
                success=False,
                error_type=error_type,
            )
        )

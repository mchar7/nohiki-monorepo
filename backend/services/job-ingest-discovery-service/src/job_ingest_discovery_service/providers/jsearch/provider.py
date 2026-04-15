"""JSearch provider: discovers jobs via the JSearch API (Google Jobs aggregator)."""

from __future__ import annotations

import asyncio
import time

from nohiki.common.v1 import CountryCode, JobBoardSource, WorkArrangement
from nohiki_observability import get_logger

from job_ingest_discovery_service.core.config import ProviderFallbackSettings
from job_ingest_discovery_service.core.models import DiscoveryRequest, DiscoveryResult, RawListing
from job_ingest_discovery_service.providers.base import BaseProvider
from job_ingest_discovery_service.providers.metrics import (
    DiscoveryMetricData,
    DiscoveryProviderMetrics,
    get_discovery_provider_metrics,
)

from .client import JSearchClient, SearchParams, get_jsearch_client
from .constants import SERVICE_NAME, TIER_HOURLY, TIER_MONTHLY
from .exceptions import JSearchRateLimitError
from .mapper import map_response_to_listings
from .models import DatePosted

logger = get_logger(__name__)

_HOURS_TO_DATE_POSTED: tuple[tuple[int, DatePosted], ...] = (
    (24, DatePosted.TODAY),
    (72, DatePosted.THREE_DAYS),
    (168, DatePosted.WEEK),
    (720, DatePosted.MONTH),
)

_COUNTRY_CODE_MAP: dict[CountryCode, str] = {
    CountryCode.USA: "us",
    CountryCode.CAN: "ca",
    CountryCode.GBR: "gb",
    CountryCode.DEU: "de",
    CountryCode.FRA: "fr",
    CountryCode.AUS: "au",
}


class JSearchProvider(BaseProvider):
    """Provider using the JSearch API for Google Jobs discovery."""

    def __init__(self, client: JSearchClient | None = None) -> None:
        """Initialize with optional client instance."""
        self._client = client or get_jsearch_client()

    @property
    def name(self) -> str:
        """Provider identifier."""
        return SERVICE_NAME

    @property
    def supported_sources(self) -> list[JobBoardSource]:
        """Supported job board sources."""
        return [JobBoardSource.GOOGLE]

    def default_priority(self) -> int:
        """Return default priority for JSearch provider."""
        return 100

    def default_fallback_settings(self) -> ProviderFallbackSettings:
        """Return fallback settings enabling JSearch by default."""
        return ProviderFallbackSettings(enabled=True)

    async def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        """Execute job discovery using JSearch API."""
        metrics = get_discovery_provider_metrics()
        start = time.monotonic()

        logger.info("Starting discovery", provider=self.name, query_id=request.query_id)

        if not self._client.is_configured:
            return self._handle_error(metrics, start, "JSearch provider not configured", "NotConfigured")

        try:
            listings = await self._execute_discovery(request)
            duration = time.monotonic() - start
            self._record_success(metrics, duration, len(listings))
            logger.info("Discovery completed", provider=self.name, query_id=request.query_id, count=len(listings))
            return DiscoveryResult(listings=listings, provider_name=self.name, duration_seconds=duration)

        except JSearchRateLimitError as exc:
            return self._handle_rate_limit(metrics, start, exc)

        except ExceptionGroup as eg:
            first = eg.exceptions[0]
            if isinstance(first, JSearchRateLimitError):
                return self._handle_rate_limit(metrics, start, first)
            logger.exception("Discovery failed", provider=self.name, query_id=request.query_id)
            return self._handle_error(metrics, start, str(first), type(first).__name__)

        except Exception as exc:
            logger.exception("Discovery failed", provider=self.name, query_id=request.query_id)
            return self._handle_error(metrics, start, str(exc), type(exc).__name__)

    async def health_check(self) -> bool:
        """Check if the provider is configured and ready."""
        return self._client.is_configured

    def _handle_rate_limit(
        self, metrics: DiscoveryProviderMetrics, start: float, exc: JSearchRateLimitError
    ) -> DiscoveryResult:
        """Build rate-limited error result."""
        metrics.record_rate_limit(self.name, "google")
        result = self._handle_error(metrics, start, f"Rate limit: {self._rate_limit_msg(exc.tier_name)}", "RateLimit")
        result.error_code = "rate_limited"
        result.retry_after_seconds = exc.retry_after_seconds
        return result

    async def _execute_discovery(self, request: DiscoveryRequest) -> list[RawListing]:
        """Execute all searches and deduplicate results."""
        params_list = self._build_search_params(request)
        if not params_list:
            return []

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(self._client.search(p)) for p in params_list]
        responses = [t.result() for t in tasks]

        all_listings: list[RawListing] = []
        for response in responses:
            all_listings.extend(map_response_to_listings(response))

        return self._deduplicate(all_listings)

    def _build_search_params(self, request: DiscoveryRequest) -> list[SearchParams]:
        """Build search parameters for each keyword."""
        date_posted = self._determine_date_posted(request.hours_old)
        work_from_home = WorkArrangement.REMOTE in request.work_arrangements
        country = self._get_country(request)
        num_pages = max(1, request.results_per_source // 10)

        return [
            SearchParams(
                query=keyword,
                num_pages=num_pages,
                country=country,
                date_posted=date_posted,
                work_from_home=work_from_home,
            )
            for keyword in request.keywords
        ]

    @staticmethod
    def _determine_date_posted(hours_old: int | None) -> DatePosted:
        """Map hours_old to JSearch date_posted filter."""
        if hours_old is None:
            return DatePosted.ALL
        for threshold, date_filter in _HOURS_TO_DATE_POSTED:
            if hours_old <= threshold:
                return date_filter
        return DatePosted.ALL

    @staticmethod
    def _get_country(request: DiscoveryRequest) -> str:
        """Extract country code from request locations."""
        for loc in request.locations:
            if loc.country != CountryCode.UNSPECIFIED:
                return _COUNTRY_CODE_MAP.get(loc.country, "us")
        return "us"

    @staticmethod
    def _deduplicate(listings: list[RawListing]) -> list[RawListing]:
        """Remove duplicates by external_id or listing_url."""
        seen: set[str] = set()
        unique: list[RawListing] = []
        for listing in listings:
            key = listing.external_id or listing.listing_url
            if key and key not in seen:
                seen.add(key)
                unique.append(listing)
        return unique

    def _record_success(self, metrics: DiscoveryProviderMetrics, duration: float, count: int) -> None:
        metrics.record_discovery(
            DiscoveryMetricData(
                provider=self.name, source="google", duration_seconds=duration, listings_found=count, success=True
            )
        )

    def _handle_error(
        self, metrics: DiscoveryProviderMetrics, start: float, error: str, error_type: str
    ) -> DiscoveryResult:
        duration = time.monotonic() - start
        metrics.record_discovery(
            DiscoveryMetricData(
                provider=self.name,
                source="google",
                duration_seconds=duration,
                listings_found=0,
                success=False,
                error_type=error_type,
            )
        )
        return DiscoveryResult(listings=[], provider_name=self.name, duration_seconds=duration, error=error)

    @staticmethod
    def _rate_limit_msg(tier_name: str) -> str:
        if tier_name == TIER_MONTHLY:
            return "Monthly quota exhausted"
        if tier_name == TIER_HOURLY:
            return "Hourly quota exhausted"
        return "API quota exceeded"

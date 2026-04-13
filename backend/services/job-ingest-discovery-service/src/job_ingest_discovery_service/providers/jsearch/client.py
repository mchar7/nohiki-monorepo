"""HTTP client for JSearch API with multi-tier rate limiting.

An async HTTP client for the JSearch API that integrates
with the nohiki-redis-utils rate limiting infrastructure to respect API quotas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Never

import httpx
from nohiki_common_exceptions import ExternalServiceError
from nohiki_observability import get_logger
from nohiki_redis_utils import RedisCache, create_cache
from nohiki_redis_utils.multi_tier_rate_limiter import (
    MultiTierRateLimiter,
    RateLimitTier,
    TierExceededBehavior,
)

from job_ingest_discovery_service.core.config import JSearchSettings, get_settings

from .constants import (
    CONTENT_TYPE_JSON,
    DEFAULT_COUNTRY,
    DEFAULT_NUM_PAGES,
    DEFAULT_PAGE,
    ENDPOINT_SEARCH,
    HEADER_ACCEPT,
    HEADER_API_KEY,
    PARAM_COUNTRY,
    PARAM_DATE_POSTED,
    PARAM_EMPLOYMENT_TYPES,
    PARAM_EXCLUDE_PUBLISHERS,
    PARAM_JOB_REQUIREMENTS,
    PARAM_LANGUAGE,
    PARAM_NUM_PAGES,
    PARAM_PAGE,
    PARAM_QUERY,
    PARAM_RADIUS,
    PARAM_WORK_FROM_HOME,
    RATE_LIMIT_BUCKET_KEY,
    RATE_LIMIT_KEY_PREFIX,
    SERVICE_NAME,
    TIER_HOURLY,
    TIER_MONTHLY,
)
from .exceptions import JSearchNotConfiguredError, JSearchRateLimitError
from .models import DatePosted, JSearchResponse

logger = get_logger(__name__)


@dataclass(frozen=True)
class SearchParams:
    """Parameters for JSearch search endpoint."""

    query: str
    page: int = DEFAULT_PAGE
    num_pages: int = DEFAULT_NUM_PAGES
    country: str = DEFAULT_COUNTRY
    language: str | None = None
    date_posted: DatePosted = DatePosted.ALL
    work_from_home: bool = False
    employment_types: str | None = None
    job_requirements: str | None = None
    radius: float | None = None
    exclude_job_publishers: str | None = None


class _JSearchClientHolder:
    """Singleton holder for JSearchClient."""

    instance: JSearchClient | None = None


class JSearchClient:
    """Async HTTP client for JSearch API with multi-tier rate limiting.

    Rate limits (configurable):
    - Monthly: 200 requests per 30 days (hard limit)
    - Hourly: 1000 requests per 60 minutes (hard limit)

    """

    def __init__(
        self,
        settings: JSearchSettings | None = None,
        cache: RedisCache | None = None,
    ) -> None:
        """Initialize JSearch client.

        Args:
            settings: JSearch-specific settings. Defaults to get_settings().jsearch.
            cache: Cache instance for rate limiting. Creates new if not provided.

        """
        self._settings = settings or get_settings().jsearch
        app_settings = get_settings()
        self._cache = cache or create_cache(
            app_settings.service_name,
            redis_url=app_settings.redis.connection_string,
        )
        self._rate_limiter = self._create_rate_limiter()
        self._http_client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """Check if the client is properly configured with an API key."""
        api_key = self._settings.api_key.get_secret_value()
        return bool(api_key) and self._settings.enabled

    async def search(self, params: SearchParams) -> JSearchResponse:
        """Search for jobs using the JSearch API.

        Args:
            params: Search parameters.

        Returns:
            JSearchResponse containing job listings.

        Raises:
            JSearchNotConfiguredError: If client not configured.
            JSearchRateLimitError: If rate limit exceeded.
            ExternalServiceError: If API request fails.

        """
        self._validate_configuration()
        await self._enforce_rate_limits()

        query_params = self._build_query_params(params)
        self._log_request_start(params)

        response_data = await self._execute_request(ENDPOINT_SEARCH, query_params)
        result = self._parse_response(response_data)

        self._log_request_success(params, result)
        return result

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def get_rate_limit_config(self) -> dict[str, dict[str, int]]:
        """Get current rate limit configuration for monitoring."""
        app_settings = get_settings()
        jsearch_api = app_settings.caching.jsearch_api
        return {
            TIER_MONTHLY: {
                "requests": jsearch_api.requests_per_day * 30,  # Monthly is 30x daily
                "window_seconds": 30 * 24 * 60 * 60,  # 30 days
            },
            TIER_HOURLY: {
                "requests": jsearch_api.requests_per_hour,
                "window_seconds": 60 * 60,  # 1 hour
            },
        }

    def _create_rate_limiter(self) -> MultiTierRateLimiter:
        """Create multi-tier rate limiter from settings."""
        app_settings = get_settings()
        jsearch_api = app_settings.caching.jsearch_api
        tiers = [
            RateLimitTier(
                name=TIER_MONTHLY,
                requests=jsearch_api.requests_per_day * 30,  # Monthly is 30x daily
                window_seconds=30 * 24 * 60 * 60,  # 30 days
                behavior=TierExceededBehavior.REJECT,
                priority=0,  # Check monthly first (hard limit)
            ),
            RateLimitTier(
                name=TIER_HOURLY,
                requests=jsearch_api.requests_per_hour,
                window_seconds=60 * 60,  # 1 hour
                behavior=TierExceededBehavior.REJECT,
                priority=1,
            ),
        ]
        return MultiTierRateLimiter(
            cache=self._cache,
            key_prefix=RATE_LIMIT_KEY_PREFIX,
            tiers=tiers,
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client (lazy initialization)."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self._settings.base_url,
                timeout=httpx.Timeout(self._settings.timeout_seconds),
                headers=self._build_default_headers(),
            )
        return self._http_client

    def _build_default_headers(self) -> dict[str, str]:
        """Build default HTTP headers for API requests."""
        return {
            HEADER_API_KEY: self._settings.api_key.get_secret_value(),
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
        }

    def _validate_configuration(self) -> None:
        """Validate client is properly configured."""
        if not self.is_configured:
            raise JSearchNotConfiguredError

    async def _enforce_rate_limits(self) -> None:
        """Check and enforce rate limits before making a request."""
        result = await self._rate_limiter.check(RATE_LIMIT_BUCKET_KEY)
        if not result.allowed:
            raise JSearchRateLimitError(
                tier_name=result.exceeded_tier or "unknown",
                retry_after_seconds=result.retry_after,
            )

    def _build_query_params(self, params: SearchParams) -> dict[str, str | int | float | bool]:
        """Build query parameters dict from SearchParams."""
        query_params: dict[str, str | int | float | bool] = {
            PARAM_QUERY: params.query,
            PARAM_PAGE: params.page,
            PARAM_NUM_PAGES: params.num_pages,
            PARAM_COUNTRY: params.country,
            PARAM_DATE_POSTED: params.date_posted.value,
        }

        self._add_optional_param(query_params, PARAM_LANGUAGE, params.language)
        self._add_optional_param(query_params, PARAM_EMPLOYMENT_TYPES, params.employment_types)
        self._add_optional_param(query_params, PARAM_JOB_REQUIREMENTS, params.job_requirements)
        self._add_optional_param(query_params, PARAM_EXCLUDE_PUBLISHERS, params.exclude_job_publishers)

        if params.work_from_home:
            query_params[PARAM_WORK_FROM_HOME] = True

        if params.radius is not None:
            query_params[PARAM_RADIUS] = params.radius

        return query_params

    @staticmethod
    def _add_optional_param(
        params: dict[str, str | int | float | bool],
        key: str,
        value: str | None,
    ) -> None:
        """Add a parameter to the dict if the value is not None."""
        if value is not None:
            params[key] = value

    async def _execute_request(
        self,
        endpoint: str,
        params: dict[str, str | int | float | bool],
    ) -> dict[str, Any]:
        """Execute HTTP request and return JSON response."""
        client = self._get_http_client()

        try:
            response = await client.get(endpoint, params=params)
        except httpx.RequestError as exc:
            self._raise_request_error(exc)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._raise_http_error(exc)

        result: dict[str, Any] = response.json()
        return result

    def _raise_http_error(self, exc: httpx.HTTPStatusError) -> Never:
        """Handle HTTP status errors from the API."""
        logger.exception(
            "JSearch API HTTP error",
            status_code=exc.response.status_code,
        )
        error_msg = f"{SERVICE_NAME} API returned {exc.response.status_code}"
        raise ExternalServiceError(
            message=error_msg,
            service_name=SERVICE_NAME,
        ) from exc

    def _raise_request_error(self, exc: httpx.RequestError) -> Never:
        """Handle connection/timeout errors."""
        logger.exception("JSearch API request failed")
        error_msg = f"{SERVICE_NAME} API request failed: {exc}"
        raise ExternalServiceError(
            message=error_msg,
            service_name=SERVICE_NAME,
        ) from exc

    @staticmethod
    def _parse_response(data: dict[str, object]) -> JSearchResponse:
        """Parse API response into typed model."""
        return JSearchResponse.model_validate(data)

    @staticmethod
    def _log_request_start(params: SearchParams) -> None:
        """Log the start of an API request."""
        logger.info(
            "Making JSearch API request",
            query=params.query,
            country=params.country,
            page=params.page,
        )

    @staticmethod
    def _log_request_success(params: SearchParams, result: JSearchResponse) -> None:
        """Log successful API request completion."""
        logger.info(
            "JSearch API request successful",
            query=params.query,
            job_count=len(result.data),
            request_id=result.request_id,
        )


def get_jsearch_client() -> JSearchClient:
    """Get the singleton JSearch client."""
    if _JSearchClientHolder.instance is None:
        _JSearchClientHolder.instance = JSearchClient()
    return _JSearchClientHolder.instance


async def reset_jsearch_client() -> None:
    """Reset the singleton client (for testing)."""
    if _JSearchClientHolder.instance is not None:
        await _JSearchClientHolder.instance.close()
    _JSearchClientHolder.instance = None

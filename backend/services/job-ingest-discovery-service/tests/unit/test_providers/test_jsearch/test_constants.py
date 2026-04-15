"""Tests for JSearch constants."""

from __future__ import annotations

from job_ingest_discovery_service.providers.jsearch.constants import (
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


class TestServiceConstants:
    """Tests for service-level constants."""

    def test_service_name(self) -> None:
        """Verify service name constant."""
        assert SERVICE_NAME == "jsearch"

    def test_rate_limit_constants(self) -> None:
        """Verify rate limit constants."""
        assert RATE_LIMIT_KEY_PREFIX == "jsearch:api"
        assert RATE_LIMIT_BUCKET_KEY == "global"
        assert TIER_MONTHLY == "monthly"
        assert TIER_HOURLY == "hourly"


class TestEndpointConstants:
    """Tests for API endpoint constants."""

    def test_search_endpoint(self) -> None:
        """Verify search endpoint."""
        assert ENDPOINT_SEARCH == "/search"


class TestHeaderConstants:
    """Tests for HTTP header constants."""

    def test_header_names(self) -> None:
        """Verify header name constants."""
        assert HEADER_API_KEY == "x-api-key"
        assert HEADER_ACCEPT == "Accept"
        assert CONTENT_TYPE_JSON == "application/json"


class TestParameterConstants:
    """Tests for query parameter constants."""

    def test_required_params(self) -> None:
        """Verify required parameter names."""
        assert PARAM_QUERY == "query"
        assert PARAM_PAGE == "page"
        assert PARAM_NUM_PAGES == "num_pages"
        assert PARAM_COUNTRY == "country"

    def test_optional_params(self) -> None:
        """Verify optional parameter names."""
        assert PARAM_DATE_POSTED == "date_posted"
        assert PARAM_LANGUAGE == "language"
        assert PARAM_WORK_FROM_HOME == "work_from_home"
        assert PARAM_EMPLOYMENT_TYPES == "employment_types"
        assert PARAM_JOB_REQUIREMENTS == "job_requirements"
        assert PARAM_RADIUS == "radius"
        assert PARAM_EXCLUDE_PUBLISHERS == "exclude_job_publishers"


class TestDefaultValues:
    """Tests for default value constants."""

    def test_defaults(self) -> None:
        """Verify default values."""
        assert DEFAULT_PAGE == 1
        assert DEFAULT_NUM_PAGES == 1
        assert DEFAULT_COUNTRY == "us"

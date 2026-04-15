from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from job_ingest_discovery_service.core.config import JSearchSettings
from job_ingest_discovery_service.providers.jsearch.client import JSearchClient, SearchParams
from job_ingest_discovery_service.providers.jsearch.exceptions import JSearchNotConfiguredError, JSearchRateLimitError
from nohiki_common_exceptions import ExternalServiceError
from pydantic import SecretStr


def _make_settings(*, api_key: str, enabled: bool = True) -> JSearchSettings:
    return JSearchSettings(
        api_key=SecretStr(api_key),
        enabled=enabled,
        base_url="https://example.com",
        timeout_seconds=1,
    )


def _make_mock_app_settings() -> MagicMock:
    """Create mock application settings with caching config."""
    mock_settings = MagicMock()
    mock_settings.caching.jsearch_api.requests_per_minute = 10
    mock_settings.caching.jsearch_api.requests_per_hour = 1000
    mock_settings.caching.jsearch_api.requests_per_day = 5000
    mock_settings.caching.jsearch_api.fallback_ttl_seconds = 86400
    return mock_settings


def test_is_configured_true_when_key_present_and_enabled() -> None:
    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=_make_mock_app_settings(),
    ):
        client = JSearchClient(settings=_make_settings(api_key="k", enabled=True), cache=MagicMock())
        client._rate_limiter = MagicMock()

        assert client.is_configured is True


def test_is_configured_false_when_missing_key() -> None:
    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=_make_mock_app_settings(),
    ):
        client = JSearchClient(settings=_make_settings(api_key="", enabled=True), cache=MagicMock())
        client._rate_limiter = MagicMock()

        assert client.is_configured is False


def test_is_configured_false_when_disabled() -> None:
    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=_make_mock_app_settings(),
    ):
        client = JSearchClient(settings=_make_settings(api_key="k", enabled=False), cache=MagicMock())
        client._rate_limiter = MagicMock()

        assert client.is_configured is False


def test_validate_configuration_raises_when_not_configured() -> None:
    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=_make_mock_app_settings(),
    ):
        client = JSearchClient(settings=_make_settings(api_key="", enabled=True), cache=MagicMock())
        client._rate_limiter = MagicMock()

        with pytest.raises(JSearchNotConfiguredError):
            client._validate_configuration()


@pytest.mark.asyncio
async def test_enforce_rate_limits_raises_rate_limit_error() -> None:
    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=_make_mock_app_settings(),
    ):
        client = JSearchClient(settings=_make_settings(api_key="k", enabled=True), cache=MagicMock())

        client._rate_limiter = MagicMock()
        client._rate_limiter.check = AsyncMock(
            return_value=SimpleNamespace(allowed=False, exceeded_tier="hourly", retry_after=123.0)
        )

        with pytest.raises(JSearchRateLimitError) as exc:
            await client._enforce_rate_limits()

        assert exc.value.tier_name == "hourly"
        assert exc.value.retry_after_seconds == pytest.approx(123.0)


def test_build_query_params_includes_optional_fields() -> None:
    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=_make_mock_app_settings(),
    ):
        client = JSearchClient(settings=_make_settings(api_key="k", enabled=True), cache=MagicMock())
        client._rate_limiter = MagicMock()

        params = SearchParams(
            query="python",
            page=2,
            num_pages=3,
            country="ca",
            language="en",
            employment_types="FULLTIME",
            job_requirements="no_degree",
            exclude_job_publishers="indeed",
            work_from_home=True,
            radius=25.5,
        )

        qp = client._build_query_params(params)

        assert qp["query"] == "python"
        assert qp["page"] == 2
        assert qp["num_pages"] == 3
        assert qp["country"] == "ca"
        assert qp["language"] == "en"
        assert qp["employment_types"] == "FULLTIME"
        assert qp["job_requirements"] == "no_degree"
        assert qp["exclude_job_publishers"] == "indeed"
        assert qp["work_from_home"] is True
        assert qp["radius"] == pytest.approx(25.5)


@pytest.mark.asyncio
async def test_execute_request_success() -> None:
    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=_make_mock_app_settings(),
    ):
        client = JSearchClient(settings=_make_settings(api_key="k", enabled=True), cache=MagicMock())
        client._rate_limiter = MagicMock()

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"status": "OK", "data": []}

        http_client = MagicMock()
        http_client.get = AsyncMock(return_value=response)

        object.__setattr__(client, "_get_http_client", MagicMock(return_value=http_client))

        result = await client._execute_request("/search", params={"query": "python"})

        assert result["status"] == "OK"


@pytest.mark.asyncio
async def test_execute_request_raises_on_request_error() -> None:
    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=_make_mock_app_settings(),
    ):
        client = JSearchClient(settings=_make_settings(api_key="k", enabled=True), cache=MagicMock())
        client._rate_limiter = MagicMock()

        req = httpx.Request("GET", "https://example.com")

        http_client = MagicMock()
        http_client.get = AsyncMock(side_effect=httpx.RequestError("boom", request=req))

        object.__setattr__(client, "_get_http_client", MagicMock(return_value=http_client))

        with pytest.raises(ExternalServiceError) as exc:
            await client._execute_request("/search", params={"query": "python"})

        assert exc.value.service_name == "jsearch"


@pytest.mark.asyncio
async def test_execute_request_raises_on_http_error() -> None:
    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=_make_mock_app_settings(),
    ):
        client = JSearchClient(settings=_make_settings(api_key="k", enabled=True), cache=MagicMock())
        client._rate_limiter = MagicMock()

        req = httpx.Request("GET", "https://example.com")
        response = httpx.Response(status_code=500, request=req)

        http_client = MagicMock()
        http_client.get = AsyncMock(return_value=response)

        object.__setattr__(client, "_get_http_client", MagicMock(return_value=http_client))

        with pytest.raises(ExternalServiceError) as exc:
            await client._execute_request("/search", params={"query": "python"})

        assert exc.value.service_name == "jsearch"


def test_get_rate_limit_config_exposes_settings() -> None:
    mock_app_settings = _make_mock_app_settings()

    with patch(
        "job_ingest_discovery_service.providers.jsearch.client.get_settings",
        return_value=mock_app_settings,
    ):
        client = JSearchClient(settings=_make_settings(api_key="k", enabled=True), cache=MagicMock())
        client._rate_limiter = MagicMock()

        config = client.get_rate_limit_config()

        # Monthly limit is calculated as daily limit times 30 days
        assert config["monthly"]["requests"] == 5000 * 30
        assert config["hourly"]["requests"] == 1000

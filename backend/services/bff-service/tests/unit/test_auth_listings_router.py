"""Tests for auth-listings router endpoint (GET /api/v1/auth-listings/).

Router-level tests mock ``compile_auth_listings`` rather than individual DB
queries, keeping the test surface focused on HTTP concerns: secret validation,
query-param validation, and response serialization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from bff_service.core.config import AuthListingsSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Constants

_COMPILE_PATH = "bff_service.api.routers.auth_listings.compile_auth_listings"
TEST_SECRET = "super-secret-test-key"

HTTP_200 = 200
HTTP_403 = 403
# RFC 9110 §15.5.23: renamed from 422 Unprocessable Entity
HTTP_422 = 422


# Helpers


def _make_test_settings(
    *,
    secret: str = TEST_SECRET,
    max_listing_age_days: int = 30,
    min_title_length: int = 10,
    primary_candidate_limit: int = 500,
    backfill_candidate_limit: int = 300,
    backfill_threshold: int = 5,
    max_listings_returned: int = 150,
    max_per_company: int = 5,
    rate_limit_per_minute: int = 60,
) -> AuthListingsSettings:
    """Build AuthListingsSettings with a known test secret."""
    return AuthListingsSettings(
        secret=secret,
        max_listing_age_days=max_listing_age_days,
        min_title_length=min_title_length,
        primary_candidate_limit=primary_candidate_limit,
        backfill_candidate_limit=backfill_candidate_limit,
        backfill_threshold=backfill_threshold,
        max_listings_returned=max_listings_returned,
        max_per_company=max_per_company,
        rate_limit_per_minute=rate_limit_per_minute,
    )


def _sample_response_dict(country: str = "USA") -> dict[str, object]:
    """Build a minimal auth-listings response as a plain dict.

    Returns a dict (not a Pydantic model) so that the mock avoids
    class identity mismatches when prior tests trigger module reloads.
    FastAPI's response_model handles validation and serialization.
    """
    return {
        "listings": [
            {
                "title": "Senior Python Engineer",
                "company_name": "Acme Corp",
                "location_raw": "San Francisco, CA",
                "work_arrangement": "REMOTE",
                "required_skills": ["Python", "FastAPI"],
                "posted_at": datetime.now(UTC).isoformat(),
                "language": "en",
            },
        ],
        "country": country,
    }


def _build_app(*, secret: str = TEST_SECRET) -> FastAPI:
    """Create a minimal FastAPI app with auth-listings router + dependency overrides.

    All identity-sensitive references (``get_settings``, ``get_async_db``) are
    imported lazily so they always resolve to the *current* module versions.
    The events test conftest evicts ``bff_service.*`` from ``sys.modules``
    after its package-scoped teardown, which would otherwise leave stale
    module-level references that no longer match ``Depends()`` targets.
    """
    from bff_service.api.deps.rate_limit import rate_limit_auth_listings
    from bff_service.api.routers.auth_listings import router
    from bff_service.core.config import Settings, get_settings
    from bff_service.core.db import get_async_db

    # Clear @cache to avoid stale singleton from prior tests
    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/auth-listings")

    settings = get_settings()
    settings.auth_listings = _make_test_settings(secret=secret)

    def _override_settings() -> Settings:
        return settings

    async def _override_db() -> AsyncMock:
        return AsyncMock()

    async def _override_rate_limit() -> None:
        """Skip the real dep: it opens live Redis sockets; tests/api/test_auth_listings_rate_limit.py covers it."""

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_async_db] = _override_db
    app.dependency_overrides[rate_limit_auth_listings] = _override_rate_limit
    return app


# Fixtures


@pytest.fixture
def test_app() -> FastAPI:
    """FastAPI app with valid test secret."""
    return _build_app()


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Test client for the auth-listings app."""
    return TestClient(test_app, raise_server_exceptions=False)


# Valid request → 200


@patch(_COMPILE_PATH, new_callable=AsyncMock)
def test_valid_request_returns_200(mock_compile: AsyncMock, client: TestClient) -> None:
    """Valid country + correct secret → 200 with listing data."""
    mock_compile.return_value = _sample_response_dict("USA")

    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "USA"},
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_200
    data = response.json()
    assert data["country"] == "USA"
    assert len(data["listings"]) == 1


@patch(_COMPILE_PATH, new_callable=AsyncMock)
def test_valid_request_gbr_returns_200(mock_compile: AsyncMock, client: TestClient) -> None:
    """GBR country code is accepted."""
    mock_compile.return_value = _sample_response_dict("GBR")

    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "GBR"},
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_200
    assert response.json()["country"] == "GBR"


# Missing secret header → 403 (uniform response; no information leak about
# whether the header is absent vs. present-but-wrong)


def test_missing_secret_header_returns_403(client: TestClient) -> None:
    """Missing X-Auth-Listings-Secret header → 403 (uniform rejection)."""
    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "USA"},
    )

    assert response.status_code == HTTP_403
    assert "Invalid auth-listings secret" in response.json()["detail"]


# Invalid secret → 403


def test_invalid_secret_returns_403(client: TestClient) -> None:
    """Wrong secret value → 403 Forbidden with uniform detail."""
    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "USA"},
        headers={"X-Auth-Listings-Secret": "wrong-secret"},
    )

    assert response.status_code == HTTP_403
    assert "Invalid auth-listings secret" in response.json()["detail"]


# Empty configured secret → 403


def test_empty_configured_secret_returns_403() -> None:
    """When the server's configured secret is empty, all requests are rejected."""
    app = _build_app(secret="")
    empty_client = TestClient(app, raise_server_exceptions=False)

    response = empty_client.get(
        "/api/v1/auth-listings/",
        params={"country": "USA"},
        headers={"X-Auth-Listings-Secret": ""},
    )

    assert response.status_code == HTTP_403
    assert "not configured" in response.json()["detail"]


def test_empty_configured_secret_rejects_any_value() -> None:
    """When configured secret is empty, even sending a non-empty value is rejected."""
    app = _build_app(secret="")
    empty_client = TestClient(app, raise_server_exceptions=False)

    response = empty_client.get(
        "/api/v1/auth-listings/",
        params={"country": "USA"},
        headers={"X-Auth-Listings-Secret": "some-value"},
    )

    assert response.status_code == HTTP_403


# Invalid country format → 422


def test_lowercase_country_returns_422(client: TestClient) -> None:
    """Lowercase country code violates ``^[A-Z]{3}$`` pattern → 422."""
    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "usa"},
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_422


def test_two_letter_country_returns_422(client: TestClient) -> None:
    """Two-letter country code violates ``^[A-Z]{3}$`` pattern → 422."""
    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "US"},
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_422


def test_four_letter_country_returns_422(client: TestClient) -> None:
    """Four-letter country code violates ``^[A-Z]{3}$`` pattern → 422."""
    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "USAA"},
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_422


def test_numeric_country_returns_422(client: TestClient) -> None:
    """Numeric country code violates ``^[A-Z]{3}$`` pattern → 422."""
    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "123"},
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_422


def test_missing_country_returns_422(client: TestClient) -> None:
    """Missing country param → 422."""
    response = client.get(
        "/api/v1/auth-listings/",
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_422


# Response structure via endpoint


@patch(_COMPILE_PATH, new_callable=AsyncMock)
def test_response_structure_matches_schema(mock_compile: AsyncMock, client: TestClient) -> None:
    """Response JSON matches AuthListingsResponse schema."""
    mock_compile.return_value = _sample_response_dict()

    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "USA"},
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_200
    listing = response.json()["listings"][0]
    assert listing["title"] == "Senior Python Engineer"
    assert listing["company_name"] == "Acme Corp"
    assert listing["required_skills"] == ["Python", "FastAPI"]
    # Weight must NOT leak through the response
    assert "weight" not in listing


@patch(_COMPILE_PATH, new_callable=AsyncMock)
def test_optional_lang_param_accepted(mock_compile: AsyncMock, client: TestClient) -> None:
    """Optional lang query param is accepted without error."""
    mock_compile.return_value = _sample_response_dict()

    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "USA", "lang": "en"},
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_200


@patch(_COMPILE_PATH, new_callable=AsyncMock)
def test_optional_lat_lon_params_accepted(mock_compile: AsyncMock, client: TestClient) -> None:
    """Optional lat/lon query params are accepted (forward compatibility)."""
    mock_compile.return_value = _sample_response_dict()

    response = client.get(
        "/api/v1/auth-listings/",
        params={"country": "USA", "lat": "37.7749", "lon": "-122.4194"},
        headers={"X-Auth-Listings-Secret": TEST_SECRET},
    )

    assert response.status_code == HTTP_200

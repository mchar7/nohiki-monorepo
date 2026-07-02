"""HTTP behavior tests for the auth-listings route limiter dependency."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from bff_service.api.deps.rate_limit import rate_limit_auth_listings
from bff_service.core.config import get_settings
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _app_with_settings(settings: object) -> FastAPI:
    app = FastAPI()

    @app.get("/limited", dependencies=[Depends(rate_limit_auth_listings)])
    async def limited() -> dict[str, bool]:
        return {"allowed": True}

    app.dependency_overrides[get_settings] = lambda: settings
    return app


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        redis=SimpleNamespace(connection_string="redis://test"),
        auth_listings=SimpleNamespace(rate_limit_per_minute=2),
    )


def test_allowed_request_reaches_the_endpoint(mocker: MockerFixture) -> None:
    """An available Worker bucket permits the request and preserves the endpoint response."""
    limiter = SimpleNamespace(check=mocker.AsyncMock(return_value=SimpleNamespace(allowed=True, retry_after=None)))
    mocker.patch("bff_service.api.deps.rate_limit.CacheFactory.create_cache", return_value=object())
    mocker.patch("bff_service.api.deps.rate_limit.create_sliding_window_limiter", return_value=limiter)

    response = TestClient(_app_with_settings(_settings())).get("/limited")

    assert response.status_code == 200
    assert response.json() == {"allowed": True}


@pytest.mark.parametrize(
    ("retry_after", "expected_header"),
    [
        pytest.param(0.0, "1", id="window-boundary-floors-to-one-second"),
        pytest.param(2.2, "3", id="fractional-delay-rounds-up"),
    ],
)
def test_exhausted_bucket_returns_429_with_safe_retry_after(
    mocker: MockerFixture,
    retry_after: float,
    expected_header: str,
) -> None:
    """Denied requests expose a positive integral backoff without invoking the endpoint."""
    limiter = SimpleNamespace(
        check=mocker.AsyncMock(return_value=SimpleNamespace(allowed=False, retry_after=retry_after))
    )
    mocker.patch("bff_service.api.deps.rate_limit.CacheFactory.create_cache", return_value=object())
    mocker.patch("bff_service.api.deps.rate_limit.create_sliding_window_limiter", return_value=limiter)

    response = TestClient(_app_with_settings(_settings())).get("/limited")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == expected_header
    assert response.json() == {"detail": "Auth-listings rate limit exceeded"}

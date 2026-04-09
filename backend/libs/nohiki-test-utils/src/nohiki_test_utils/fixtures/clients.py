"""Shared client fixtures for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def fastapi_app() -> FastAPI:
    """Provide a FastAPI app instance. Override this in service-specific conftest.py."""
    # This is a placeholder that should be overridden by each service
    app = FastAPI(title="Test App")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture
def test_client(fastapi_app: FastAPI) -> Generator[TestClient]:
    """Provide a TestClient for the FastAPI app."""
    with TestClient(fastapi_app) as client:
        yield client


@pytest.fixture
async def async_client(fastapi_app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    """Provide an async HTTP client for the FastAPI app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.fixture
async def async_client_with_db(fastapi_app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    """Provide an async HTTP client with real database session.

    Note: Each service should override this to use their specific get_async_db dependency.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app),
        base_url="http://testserver",
    ) as client:
        yield client

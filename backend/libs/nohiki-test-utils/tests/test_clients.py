"""Tests for nohiki_test_utils.fixtures.clients module."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestFastapiAppFixture:
    """Tests for the default fastapi_app fixture."""

    def test_fixture_provides_fastapi_app(self, fastapi_app: FastAPI) -> None:
        """The fastapi_app pytest fixture provides a FastAPI instance."""
        assert isinstance(fastapi_app, FastAPI)

    def test_fixture_health_endpoint_responds(self, fastapi_app: FastAPI) -> None:
        """The default app returned by fastapi_app has a working /health route."""
        with TestClient(fastapi_app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestTestClientFixture:
    """Tests for the test_client fixture."""

    def test_fixture_provides_test_client(self, test_client: TestClient) -> None:
        """test_client fixture provides an httpx-backed TestClient."""
        assert isinstance(test_client, TestClient)

    def test_test_client_health_check(self, test_client: TestClient) -> None:
        """test_client can make GET /health and receive 200."""
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_test_client_returns_404_for_unknown_path(self, test_client: TestClient) -> None:
        """test_client returns 404 for routes not registered on the default app."""
        response = test_client.get("/nonexistent")
        assert response.status_code == 404


class TestAsyncClientFixture:
    """Tests for the async_client fixture."""

    @pytest.mark.asyncio
    async def test_fixture_provides_async_client(self, async_client: httpx.AsyncClient) -> None:
        """async_client fixture provides an httpx.AsyncClient instance."""
        assert isinstance(async_client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_async_client_health_check(self, async_client: httpx.AsyncClient) -> None:
        """async_client can GET /health asynchronously."""
        response = await async_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_async_client_base_url(self, async_client: httpx.AsyncClient) -> None:
        """async_client is configured with the testserver base URL."""
        assert "testserver" in str(async_client.base_url)


class TestAsyncClientWithDbFixture:
    """Tests for the async_client_with_db fixture."""

    @pytest.mark.asyncio
    async def test_fixture_provides_async_client(self, async_client_with_db: httpx.AsyncClient) -> None:
        """async_client_with_db fixture provides an httpx.AsyncClient instance."""
        assert isinstance(async_client_with_db, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_async_client_with_db_health_check(self, async_client_with_db: httpx.AsyncClient) -> None:
        """async_client_with_db can GET /health successfully."""
        response = await async_client_with_db.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_async_client_with_db_base_url(self, async_client_with_db: httpx.AsyncClient) -> None:
        """async_client_with_db uses the testserver base URL."""
        assert "testserver" in str(async_client_with_db.base_url)

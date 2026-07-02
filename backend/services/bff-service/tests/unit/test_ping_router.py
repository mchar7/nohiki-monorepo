"""Tests for ping router."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient


@pytest.fixture
def test_app() -> FastAPI:
    """Create a test FastAPI app with ping router."""
    from bff_service.api.routers.ping import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(test_app)


def test_ping_returns_ok(client: TestClient) -> None:
    """Test that ping endpoint returns ok status."""
    response = client.get("/api/ping")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data == {"status": "ok"}

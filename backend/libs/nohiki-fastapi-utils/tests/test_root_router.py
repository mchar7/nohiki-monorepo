"""Tests for root router utilities."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from nohiki_fastapi_utils.root_router import build_root_router


class TestBuildRootRouter:
    """Tests for build_root_router function."""

    def test_creates_router_with_root_endpoint(self) -> None:
        """Test that router has / endpoint."""
        router = build_root_router("test-service", "1.0.0")

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/")
        assert response.status_code == 200

    def test_root_endpoint_returns_service_info(self) -> None:
        """Test that root endpoint returns service information."""
        router = build_root_router("my-service", "2.0.0")

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/")
        data = response.json()

        assert data["service"] == "my-service"
        assert data["version"] == "2.0.0"
        assert data["status"] == "running"

    def test_different_service_names(self) -> None:
        """Test router with different service names."""
        router1 = build_root_router("service-a", "1.0.0")
        router2 = build_root_router("service-b", "2.0.0")

        app1 = FastAPI()
        app1.include_router(router1)
        client1 = TestClient(app1)

        app2 = FastAPI()
        app2.include_router(router2)
        client2 = TestClient(app2)

        response1 = client1.get("/")
        response2 = client2.get("/")

        assert response1.json()["service"] == "service-a"
        assert response2.json()["service"] == "service-b"

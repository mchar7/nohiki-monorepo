"""Tests for CSRF protection middleware."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from nohiki_fastapi_utils.csrf import (
    CSRF_PROTECTED_METHODS,
    SAFE_FETCH_SITES,
    CSRFMiddleware,
    validate_csrf,
)
from starlette.requests import Request


class TestCSRFConstants:
    """Tests for CSRF constants."""

    def test_protected_methods(self) -> None:
        """Test CSRF protected methods."""
        assert "POST" in CSRF_PROTECTED_METHODS
        assert "PUT" in CSRF_PROTECTED_METHODS
        assert "PATCH" in CSRF_PROTECTED_METHODS
        assert "DELETE" in CSRF_PROTECTED_METHODS
        assert "GET" not in CSRF_PROTECTED_METHODS
        assert "HEAD" not in CSRF_PROTECTED_METHODS
        assert "OPTIONS" not in CSRF_PROTECTED_METHODS

    def test_safe_fetch_sites(self) -> None:
        """Test safe Sec-Fetch-Site values."""
        assert "same-origin" in SAFE_FETCH_SITES
        assert "same-site" in SAFE_FETCH_SITES
        assert "cross-site" not in SAFE_FETCH_SITES


class TestCSRFMiddleware:
    """Tests for CSRFMiddleware."""

    def test_allows_get_requests(self) -> None:
        """Test that GET requests are allowed without validation."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200

    def test_allows_post_without_cookies(self) -> None:
        """Test that POST requests without cookies are allowed."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.post("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app, cookies={})
        response = client.post("/test")
        assert response.status_code == 200

    def test_allows_post_with_valid_origin(self) -> None:
        """Test that POST requests with valid origin are allowed."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.post("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app, cookies={"session": "test"})
        response = client.post("/test", headers={"Origin": "https://example.com"})
        assert response.status_code == 200

    def test_blocks_post_with_invalid_origin(self) -> None:
        """Test that POST requests with invalid origin are blocked."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.post("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        with TestClient(app, cookies={"session": "test"}, raise_server_exceptions=False) as client:
            response = client.post("/test", headers={"Origin": "https://evil.com"})
            assert response.status_code == 403

    def test_allows_post_with_same_origin_fetch_site(self) -> None:
        """Test that POST with same-origin Sec-Fetch-Site is allowed."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.post("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app, cookies={"session": "test"})
        response = client.post("/test", headers={"Sec-Fetch-Site": "same-origin"})
        assert response.status_code == 200

    def test_allows_post_with_same_site_fetch_site(self) -> None:
        """Test that POST with same-site Sec-Fetch-Site is allowed."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.post("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app, cookies={"session": "test"})
        response = client.post("/test", headers={"Sec-Fetch-Site": "same-site"})
        assert response.status_code == 200

    def test_blocks_post_with_cross_site_fetch_site(self) -> None:
        """Test that POST with cross-site Sec-Fetch-Site is blocked."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.post("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        with TestClient(app, cookies={"session": "test"}, raise_server_exceptions=False) as client:
            response = client.post("/test", headers={"Sec-Fetch-Site": "cross-site"})
            assert response.status_code == 403

    def test_put_method_protected(self) -> None:
        """Test that PUT method is protected."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.put("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        with TestClient(app, cookies={"session": "test"}, raise_server_exceptions=False) as client:
            response = client.put("/test", headers={"Origin": "https://evil.com"})
            assert response.status_code == 403

    def test_patch_method_protected(self) -> None:
        """Test that PATCH method is protected."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.patch("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        with TestClient(app, cookies={"session": "test"}, raise_server_exceptions=False) as client:
            response = client.patch("/test", headers={"Origin": "https://evil.com"})
            assert response.status_code == 403

    def test_delete_method_protected(self) -> None:
        """Test that DELETE method is protected."""
        app = FastAPI()
        app.add_middleware(CSRFMiddleware, allowed_origins=["https://example.com"])

        @app.delete("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        with TestClient(app, cookies={"session": "test"}, raise_server_exceptions=False) as client:
            response = client.delete("/test", headers={"Origin": "https://evil.com"})
            assert response.status_code == 403


class TestValidateCsrf:
    """Tests for validate_csrf function."""

    def test_allows_valid_origin(self) -> None:
        """Test that valid origin passes validation."""
        app = FastAPI()

        @app.post("/test")
        async def test_endpoint(request: Request) -> dict[str, str]:
            validate_csrf(request, ["https://example.com"])
            return {"status": "ok"}

        client = TestClient(app)
        response = client.post("/test", headers={"Origin": "https://example.com"})
        assert response.status_code == 200

    def test_blocks_invalid_origin(self) -> None:
        """Test that invalid origin fails validation."""
        app = FastAPI()

        @app.post("/test")
        async def test_endpoint(request: Request) -> dict[str, str]:
            validate_csrf(request, ["https://example.com"])
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/test", headers={"Origin": "https://evil.com"})
        assert response.status_code == 403

    def test_allows_no_origin(self) -> None:
        """Test that requests without origin pass validation."""
        app = FastAPI()

        @app.post("/test")
        async def test_endpoint(request: Request) -> dict[str, str]:
            validate_csrf(request, ["https://example.com"])
            return {"status": "ok"}

        client = TestClient(app)
        response = client.post("/test")
        assert response.status_code == 200

    def test_allows_same_origin_fetch_site(self) -> None:
        """Test that same-origin Sec-Fetch-Site passes validation."""
        app = FastAPI()

        @app.post("/test")
        async def test_endpoint(request: Request) -> dict[str, str]:
            validate_csrf(request, ["https://example.com"])
            return {"status": "ok"}

        client = TestClient(app)
        response = client.post("/test", headers={"Sec-Fetch-Site": "same-origin"})
        assert response.status_code == 200

    def test_blocks_cross_site_fetch_site(self) -> None:
        """Test that cross-site Sec-Fetch-Site fails validation."""
        app = FastAPI()

        @app.post("/test")
        async def test_endpoint(request: Request) -> dict[str, str]:
            validate_csrf(request, ["https://example.com"])
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/test", headers={"Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 403


class TestCreateCSRFMiddleware:
    """Tests for create_csrf_middleware factory."""

    def test_creates_configured_middleware(self) -> None:
        """create_csrf_middleware returns a middleware class with pre-configured origins."""
        from nohiki_fastapi_utils.csrf import create_csrf_middleware

        middleware_cls = create_csrf_middleware(["https://example.com"])
        app = FastAPI()
        app.add_middleware(middleware_cls)

        @app.post("/test")
        async def test_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app)
        response = client.post(
            "/test",
            headers={"Origin": "https://example.com", "Sec-Fetch-Site": "same-origin"},
        )
        assert response.status_code == 200

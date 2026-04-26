"""Unit tests for user_auth_service.core.csrf module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, status
from starlette.requests import Request
from starlette.responses import Response
from user_auth_service.core.csrf import (
    CSRF_PROTECTED_METHODS,
    SAFE_FETCH_SITES,
    CSRFMiddleware,
    validate_csrf,
)


class TestCSRFMiddleware:
    """Tests for CSRFMiddleware class."""

    @pytest.mark.asyncio
    async def test_allows_get_requests_without_validation(self) -> None:
        """GET requests bypass CSRF validation."""
        app = MagicMock()
        middleware = CSRFMiddleware(app, allowed_origins=["http://localhost:3000"])

        request = MagicMock(spec=Request)
        request.method = "GET"
        request.cookies = {"session": "value"}

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        # call_next should be called without CSRF validation
        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_allows_head_requests_without_validation(self) -> None:
        """HEAD requests bypass CSRF validation."""
        app = MagicMock()
        middleware = CSRFMiddleware(app, allowed_origins=["http://localhost:3000"])

        request = MagicMock(spec=Request)
        request.method = "HEAD"
        request.cookies = {"session": "value"}

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_allows_options_requests_without_validation(self) -> None:
        """OPTIONS requests bypass CSRF validation."""
        app = MagicMock()
        middleware = CSRFMiddleware(app, allowed_origins=["http://localhost:3000"])

        request = MagicMock(spec=Request)
        request.method = "OPTIONS"
        request.cookies = {"session": "value"}

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_allows_post_requests_without_cookies(self) -> None:
        """POST requests without cookies bypass CSRF validation."""
        app = MagicMock()
        middleware = CSRFMiddleware(app, allowed_origins=["http://localhost:3000"])

        request = MagicMock(spec=Request)
        request.method = "POST"
        request.cookies = {}  # No cookies

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_validates_origin_header_for_post_with_cookies(self) -> None:
        """POST requests with cookies validate Origin header."""
        app = MagicMock()
        allowed_origins = ["http://localhost:3000"]
        middleware = CSRFMiddleware(app, allowed_origins=allowed_origins)

        request = MagicMock(spec=Request)
        request.method = "POST"
        request.cookies = {"session": "value"}
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "http://localhost:3000" if k == "origin" else None)

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_rejects_invalid_origin_header(self) -> None:
        """POST requests with invalid Origin are rejected with 403 response."""
        app = MagicMock()
        allowed_origins = ["http://localhost:3000"]
        middleware = CSRFMiddleware(app, allowed_origins=allowed_origins)

        request = MagicMock(spec=Request)
        request.method = "POST"
        request.cookies = {"session": "value"}
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "http://evil.com" if k == "origin" else None)
        request.url = MagicMock()
        request.url.path = "/api/v1/test"

        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_validates_sec_fetch_site_same_origin(self) -> None:
        """POST requests with Sec-Fetch-Site: same-origin are allowed."""
        app = MagicMock()
        middleware = CSRFMiddleware(app, allowed_origins=["http://localhost:3000"])

        request = MagicMock(spec=Request)
        request.method = "POST"
        request.cookies = {"session": "value"}
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "same-origin" if k == "sec-fetch-site" else None)

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_validates_sec_fetch_site_same_site(self) -> None:
        """POST requests with Sec-Fetch-Site: same-site are allowed."""
        app = MagicMock()
        middleware = CSRFMiddleware(app, allowed_origins=["http://localhost:3000"])

        request = MagicMock(spec=Request)
        request.method = "POST"
        request.cookies = {"session": "value"}
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "same-site" if k == "sec-fetch-site" else None)

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_rejects_invalid_sec_fetch_site(self) -> None:
        """POST requests with invalid Sec-Fetch-Site are rejected with 403 response."""
        app = MagicMock()
        middleware = CSRFMiddleware(app, allowed_origins=["http://localhost:3000"])

        request = MagicMock(spec=Request)
        request.method = "POST"
        request.cookies = {"session": "value"}
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "cross-site" if k == "sec-fetch-site" else None)
        request.url = MagicMock()
        request.url.path = "/api/v1/test"

        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_cookie_mutation_without_browser_provenance(self) -> None:
        """Cookie-authenticated mutations require Origin or Sec-Fetch-Site provenance."""
        app = MagicMock()
        middleware = CSRFMiddleware(app, allowed_origins=["http://localhost:3000"])

        request = MagicMock(spec=Request)
        request.method = "POST"
        request.cookies = {"session": "value"}
        request.headers = MagicMock()
        request.headers.get = MagicMock(return_value=None)
        request.url = MagicMock()
        request.url.path = "/api/v1/test"

        call_next = AsyncMock()

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_validates_put_requests(self) -> None:
        """PUT requests are validated for CSRF."""
        app = MagicMock()
        allowed_origins = ["http://localhost:3000"]
        middleware = CSRFMiddleware(app, allowed_origins=allowed_origins)

        request = MagicMock(spec=Request)
        request.method = "PUT"
        request.cookies = {"session": "value"}
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "http://localhost:3000" if k == "origin" else None)

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_validates_patch_requests(self) -> None:
        """PATCH requests are validated for CSRF."""
        app = MagicMock()
        allowed_origins = ["http://localhost:3000"]
        middleware = CSRFMiddleware(app, allowed_origins=allowed_origins)

        request = MagicMock(spec=Request)
        request.method = "PATCH"
        request.cookies = {"session": "value"}
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "http://localhost:3000" if k == "origin" else None)

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_validates_delete_requests(self) -> None:
        """DELETE requests are validated for CSRF."""
        app = MagicMock()
        allowed_origins = ["http://localhost:3000"]
        middleware = CSRFMiddleware(app, allowed_origins=allowed_origins)

        request = MagicMock(spec=Request)
        request.method = "DELETE"
        request.cookies = {"session": "value"}
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "http://localhost:3000" if k == "origin" else None)

        call_next = AsyncMock(return_value=Response())

        response = await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200


class TestValidateCSRF:
    """Tests for validate_csrf function."""

    def test_validates_valid_origin(self) -> None:
        """Accepts valid origin."""
        request = MagicMock(spec=Request)
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "http://localhost:3000" if k == "origin" else None)

        allowed_origins = ["http://localhost:3000"]

        # Should not raise
        validate_csrf(request, allowed_origins)

    def test_rejects_invalid_origin(self) -> None:
        """Rejects invalid origin."""
        request = MagicMock(spec=Request)
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "http://evil.com" if k == "origin" else None)

        allowed_origins = ["http://localhost:3000"]

        with pytest.raises(HTTPException) as exc_info:
            validate_csrf(request, allowed_origins)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Invalid origin" in str(exc_info.value.detail)

    def test_validates_valid_sec_fetch_site(self) -> None:
        """Accepts valid Sec-Fetch-Site."""
        request = MagicMock(spec=Request)
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "same-origin" if k == "sec-fetch-site" else None)

        allowed_origins = ["http://localhost:3000"]

        # Should not raise
        validate_csrf(request, allowed_origins)

    def test_rejects_missing_browser_provenance(self) -> None:
        """Direct CSRF validation rejects cookie-style mutations without provenance metadata."""
        request = MagicMock(spec=Request)
        request.headers = MagicMock()
        request.headers.get = MagicMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            validate_csrf(request, ["http://localhost:3000"])

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc_info.value.detail == "Request origin required"

    def test_rejects_invalid_sec_fetch_site(self) -> None:
        """Rejects invalid Sec-Fetch-Site."""
        request = MagicMock(spec=Request)
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda k: "cross-site" if k == "sec-fetch-site" else None)

        allowed_origins = ["http://localhost:3000"]

        with pytest.raises(HTTPException) as exc_info:
            validate_csrf(request, allowed_origins)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Cross-site request not allowed" in str(exc_info.value.detail)


class TestCSRFConstants:
    """Tests for CSRF module constants."""

    def test_csrf_protected_methods_includes_expected_methods(self) -> None:
        """CSRF_PROTECTED_METHODS contains the right HTTP methods."""
        assert "POST" in CSRF_PROTECTED_METHODS
        assert "PUT" in CSRF_PROTECTED_METHODS
        assert "PATCH" in CSRF_PROTECTED_METHODS
        assert "DELETE" in CSRF_PROTECTED_METHODS
        # Safe methods should not be included
        assert "GET" not in CSRF_PROTECTED_METHODS
        assert "HEAD" not in CSRF_PROTECTED_METHODS
        assert "OPTIONS" not in CSRF_PROTECTED_METHODS

    def test_safe_fetch_sites_includes_expected_values(self) -> None:
        """SAFE_FETCH_SITES contains the right values."""
        assert "same-origin" in SAFE_FETCH_SITES
        assert "same-site" in SAFE_FETCH_SITES
        # Cross-site should not be safe
        assert "cross-site" not in SAFE_FETCH_SITES

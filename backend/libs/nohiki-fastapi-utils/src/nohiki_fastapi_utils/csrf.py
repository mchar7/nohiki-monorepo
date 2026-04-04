"""CSRF protection middleware.

Implements Origin header validation for cookie-based authentication.
No double-submit tokens - relies on:
- SameSite=Lax cookies
- Origin header validation
- Sec-Fetch-Site validation
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

# HTTP methods that require CSRF protection
CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Safe Sec-Fetch-Site values
SAFE_FETCH_SITES = frozenset({"same-origin", "same-site"})


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF protection middleware for cookie-based authentication.

    Validates:
    1. Origin header matches allowed list
    2. Sec-Fetch-Site is same-origin or same-site (if present)

    Skip validation for:
    - GET, HEAD, OPTIONS requests
    - Requests without cookies (not authenticated)
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        """Initialize CSRF middleware.

        Args:
            app: The ASGI application
            allowed_origins: List of allowed origin URLs

        """
        super().__init__(app)
        self._allowed_origins = frozenset(allowed_origins)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process the request with CSRF validation."""
        # Skip validation for safe methods
        if request.method not in CSRF_PROTECTED_METHODS:
            return await call_next(request)

        # Skip if no cookies (not a cookie-authenticated request)
        if not request.cookies:
            return await call_next(request)

        # Validate Origin header
        origin = request.headers.get("origin")
        sec_fetch_site = request.headers.get("sec-fetch-site")

        # If Origin is present, it must be in allowed list
        if origin and origin not in self._allowed_origins:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Invalid origin"},
            )

        # If Sec-Fetch-Site is present, it must be same-origin or same-site
        if sec_fetch_site and sec_fetch_site not in SAFE_FETCH_SITES:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Cross-site request not allowed"},
            )

        return await call_next(request)


def validate_csrf(request: Request, allowed_origins: list[str]) -> None:
    """Validate CSRF for a single request (for use in route dependencies).

    Args:
        request: The incoming request
        allowed_origins: List of allowed origin URLs

    Raises:
        HTTPException: If CSRF validation fails

    """
    origin = request.headers.get("origin")
    sec_fetch_site = request.headers.get("sec-fetch-site")

    if origin and origin not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid origin",
        )

    if sec_fetch_site and sec_fetch_site not in SAFE_FETCH_SITES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-site request not allowed",
        )


def create_csrf_middleware(allowed_origins: list[str]) -> type[CSRFMiddleware]:
    """Create a CSRFMiddleware class with allowed_origins pre-bound.

    This factory function creates a middleware class that can be used with
    FastAPI/Starlette without ParamSpec type issues.

    Args:
        allowed_origins: List of allowed origin URLs.

    Returns:
        A CSRFMiddleware subclass with allowed_origins pre-configured.

    """

    class ConfiguredCSRFMiddleware(CSRFMiddleware):
        """Pre-configured CSRF middleware."""

        def __init__(self, app: ASGIApp) -> None:
            super().__init__(app, allowed_origins)

    return ConfiguredCSRFMiddleware

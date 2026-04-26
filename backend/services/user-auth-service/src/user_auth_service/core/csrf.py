"""CSRF protection middleware.

Implements Origin header validation for cookie-based authentication.
No double-submit tokens - relies on:
- SameSite=Lax cookies
- Origin header validation
- Sec-Fetch-Site validation
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from nohiki_observability import get_logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = get_logger(__name__)

# HTTP methods that require CSRF protection
CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Safe Sec-Fetch-Site values
SAFE_FETCH_SITES = frozenset({"same-origin", "same-site"})


def _csrf_error_response(request: Request, message: str) -> JSONResponse:
    """Create a standardized 403 CSRF error response."""
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content=jsonable_encoder(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": 403,
                "error": "FORBIDDEN",
                "message": message,
                "path": str(request.url.path),
                "details": None,
            }
        ),
    )


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
        logger.info("CSRF middleware ready", allowed_origins=allowed_origins)

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
            logger.warning(
                "CSRF: Invalid Origin header",
                origin=origin,
                allowed=list(self._allowed_origins),
            )
            return _csrf_error_response(request, "Invalid origin")

        # If Sec-Fetch-Site is present, it must be same-origin or same-site
        if sec_fetch_site and sec_fetch_site not in SAFE_FETCH_SITES:
            logger.warning(
                "CSRF: Invalid Sec-Fetch-Site header",
                sec_fetch_site=sec_fetch_site,
            )
            return _csrf_error_response(request, "Cross-site request not allowed")

        # Cookie-authenticated mutations must carry browser provenance.
        # Headerless API clients should authenticate without browser cookies.
        if not origin and not sec_fetch_site:
            logger.warning("CSRF: Missing Origin and Sec-Fetch-Site headers")
            return _csrf_error_response(request, "Request origin required")

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

    if not origin and not sec_fetch_site:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin required",
        )

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

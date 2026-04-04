"""FastAPI utilities for the Nohiki platform."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import Header, HTTPException, status
from nohiki_observability import (
    CORRELATION_ID_HEADER,
    CorrelationIdMiddleware,
    get_correlation_id,
    set_correlation_id,
)

from .csrf import CSRFMiddleware, create_csrf_middleware, validate_csrf
from .errors import setup_error_handlers
from .health_router import (
    ReadinessGateProtocol,
    build_probe_health_router,
    build_stateless_health_router,
)
from .pagination import PaginatedResponse, PaginationParams, SortParams
from .root_router import build_root_router


def get_current_user_id_from_header(
    x_account_id: str | None = Header(default=None, alias="X-Account-Id"),
) -> UUID:
    """Extract and validate user ID from X-Account-Id header."""
    if not x_account_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Account-Id header",
        )

    try:
        return UUID(x_account_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-Account-Id header",
        ) from e


_JWT_AVAILABLE = False
_RATE_LIMITER_AVAILABLE = False

if TYPE_CHECKING:
    from .jwks import (
        JWKSConfig,
        JWKSVerificationError,
        JWKSVerifier,
        JWTClaims,
        get_current_user_claims,
        get_current_user_id_from_cookie,
        get_jwks_verifier,
        init_jwks_verifier,
    )
    from .rate_limiter import get_client_id, rate_limit, setup_rate_limiting

if not TYPE_CHECKING:
    # Runtime: attempt import, fall back to None for services without [cache] extra
    get_client_id = None
    rate_limit = None
    setup_rate_limiting = None

    try:
        from .rate_limiter import get_client_id, rate_limit, setup_rate_limiting

        _RATE_LIMITER_AVAILABLE = True
    except ImportError:
        pass

    # Runtime: attempt import, fall back to None for services without [jwt] extra
    JWKSConfig = None
    JWKSVerificationError = None
    JWKSVerifier = None
    JWTClaims = None
    get_current_user_claims = None
    get_current_user_id_from_cookie = None
    get_jwks_verifier = None
    init_jwks_verifier = None

    try:
        from .jwks import (
            JWKSConfig,
            JWKSVerificationError,
            JWKSVerifier,
            JWTClaims,
            get_current_user_claims,
            get_current_user_id_from_cookie,
            get_jwks_verifier,
            init_jwks_verifier,
        )

        _JWT_AVAILABLE = True
    except ImportError:
        pass

__version__ = "0.1.0"

__all__ = [
    "CORRELATION_ID_HEADER",
    "CSRFMiddleware",
    "CorrelationIdMiddleware",
    "PaginatedResponse",
    "PaginationParams",
    "ReadinessGateProtocol",
    "SortParams",
    "build_probe_health_router",
    "build_root_router",
    "build_stateless_health_router",
    "create_csrf_middleware",
    "get_correlation_id",
    "get_current_user_id_from_header",
    "set_correlation_id",
    "setup_error_handlers",
    "validate_csrf",
]

if _RATE_LIMITER_AVAILABLE:
    __all__ += [
        "get_client_id",
        "rate_limit",
        "setup_rate_limiting",
    ]

if _JWT_AVAILABLE:
    __all__ += [
        "JWKSConfig",
        "JWKSVerificationError",
        "JWKSVerifier",
        "JWTClaims",
        "get_current_user_claims",
        "get_current_user_id_from_cookie",
        "get_jwks_verifier",
        "init_jwks_verifier",
    ]

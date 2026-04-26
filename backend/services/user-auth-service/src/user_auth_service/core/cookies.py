"""Secure cookie utilities for JWT authentication.

Uses __Host- prefix cookies with:
- HttpOnly: Prevents JavaScript access
- Secure: HTTPS only (except local dev)
- SameSite=Lax: CSRF protection
- Path=/: Available for all paths
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from fastapi import Response

if TYPE_CHECKING:
    from user_auth_service.core.config import Settings


def set_access_token_cookie(
    response: Response,
    token: str,
    settings: Settings,
) -> None:
    """Set the access token cookie with secure defaults.

    Args:
        response: FastAPI response object
        token: The JWT access token
        settings: Application settings

    """
    response.set_cookie(
        key=settings.cookie.access_token_name,
        value=token,
        httponly=True,
        secure=settings.cookie.secure,
        samesite=settings.cookie.samesite,
        path="/",
        domain=settings.cookie.domain,
        max_age=settings.jwt.access_token_expire_minutes * 60,
    )


def set_refresh_token_cookie(
    response: Response,
    token: str,
    settings: Settings,
) -> None:
    """Set the refresh token cookie with secure defaults.

    Args:
        response: FastAPI response object
        token: The opaque refresh token
        settings: Application settings

    """
    response.set_cookie(
        key=settings.cookie.refresh_token_name,
        value=token,
        httponly=True,
        secure=settings.cookie.secure,
        samesite=settings.cookie.samesite,
        path="/",
        domain=settings.cookie.domain,
        max_age=settings.jwt.refresh_token_expire_days * 24 * 60 * 60,
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    """Clear both access and refresh token cookies (logout).

    Args:
        response: FastAPI response object
        settings: Application settings

    """
    # Clear access token
    response.delete_cookie(
        key=settings.cookie.access_token_name,
        path="/",
        domain=settings.cookie.domain,
        secure=settings.cookie.secure,
        httponly=True,
        samesite=settings.cookie.samesite,
    )

    # Clear refresh token
    response.delete_cookie(
        key=settings.cookie.refresh_token_name,
        path="/",
        domain=settings.cookie.domain,
        secure=settings.cookie.secure,
        httponly=True,
        samesite=settings.cookie.samesite,
    )


def get_access_token_from_cookie(
    cookies: dict[str, str],
    settings: Settings,
) -> str | None:
    """Extract access token from cookies.

    Args:
        cookies: Request cookies dictionary
        settings: Application settings

    Returns:
        Access token string or None if not present

    """
    return cookies.get(settings.cookie.access_token_name)


def get_refresh_token_from_cookie(
    cookies: dict[str, str],
    settings: Settings,
) -> str | None:
    """Extract refresh token from cookies.

    Args:
        cookies: Request cookies dictionary
        settings: Application settings

    Returns:
        Refresh token string or None if not present

    """
    return cookies.get(settings.cookie.refresh_token_name)


MAX_OAUTH_STATE_COOKIES = 4


def get_oauth_state_cookie_name(state: str, settings: Settings) -> str:
    """Derive a non-secret, collision-resistant cookie name for an OAuth state."""
    state_digest = sha256(state.encode()).hexdigest()
    return f"{settings.cookie.oauth_state_name}_{state_digest}"


def clear_excess_oauth_state_cookies(
    response: Response,
    cookies: dict[str, str],
    settings: Settings,
) -> None:
    """Make room for one new OAuth flow while keeping cookie growth bounded."""
    prefix = f"{settings.cookie.oauth_state_name}_"
    active_names = [name for name in cookies if name.startswith(prefix)]
    excess_count = max(0, len(active_names) - MAX_OAUTH_STATE_COOKIES + 1)
    for name in active_names[:excess_count]:
        response.delete_cookie(
            key=name,
            path="/",
            secure=settings.cookie.secure,
            httponly=True,
            samesite="lax",
        )


def set_oauth_state_cookie(response: Response, state: str, settings: Settings) -> None:
    """Bind an OAuth authorization flow to the initiating browser."""
    response.set_cookie(
        key=get_oauth_state_cookie_name(state, settings),
        value=state,
        httponly=True,
        secure=settings.cookie.secure,
        samesite="lax",
        path="/",
        max_age=settings.oauth.state_ttl,
    )


def clear_oauth_state_cookie(response: Response, state: str, settings: Settings) -> None:
    """Clear only the browser binding for the specified OAuth flow."""
    response.delete_cookie(
        key=get_oauth_state_cookie_name(state, settings),
        path="/",
        secure=settings.cookie.secure,
        httponly=True,
        samesite="lax",
    )


def get_oauth_state_from_cookie(
    cookies: dict[str, str],
    state: str,
    settings: Settings,
) -> str | None:
    """Extract only the browser-binding cookie matching the callback state."""
    return cookies.get(get_oauth_state_cookie_name(state, settings))

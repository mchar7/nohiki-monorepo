"""Auth-listings secret validation dependency."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from bff_service.core.config import Settings, get_settings


async def validate_auth_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    x_auth_listings_secret: Annotated[str, Header(alias="X-Auth-Listings-Secret")] = "",
) -> None:
    """Validate the auth-listings shared secret via timing-safe comparison.

    Returns a uniform 403 for every failure mode so callers cannot distinguish
    "header missing" from "header present but wrong": narrows the information
    surface exposed to unauthenticated clients. The header defaults to an empty
    string so a missing header routes through this dependency (and yields 403)
    rather than hitting FastAPI's 422 validation path.

    Args:
        settings: Application settings containing the expected secret.
        x_auth_listings_secret: Secret from the Worker's request header; empty
            when the header is absent.

    Raises:
        HTTPException: 403 if the configured secret is empty, the header is
            missing/empty, or the timing-safe comparison fails.
    """
    expected = settings.auth_listings.secret
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auth-listings secret not configured",
        )
    if not x_auth_listings_secret or not hmac.compare_digest(x_auth_listings_secret, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid auth-listings secret",
        )

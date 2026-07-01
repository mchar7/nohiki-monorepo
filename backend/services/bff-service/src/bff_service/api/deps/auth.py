"""BFF-local authentication dependencies with durable token revocation checks."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from nohiki_fastapi_utils import JWTClaims
from nohiki_fastapi_utils import get_current_user_claims as get_verified_user_claims
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.core.db import get_async_db
from bff_service.services.auth_revocation import is_access_token_revoked


async def get_current_user_claims(
    claims: Annotated[JWTClaims, Depends(get_verified_user_claims)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> JWTClaims:
    """Return verified claims only while their local revocation is inactive."""
    try:
        user_id = UUID(claims.sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
        ) from exc

    try:
        UUID(claims.jti)
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from exc

    try:
        revoked = await is_access_token_revoked(
            db,
            user_id=user_id,
            jti=claims.jti,
            issued_at=datetime.fromtimestamp(claims.iat, tz=UTC),
            session_family_id=claims.session_family_id,
        )
    except (SQLAlchemyError, OverflowError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication state unavailable",
        ) from exc

    if revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        )
    return claims


async def get_current_user_id_from_cookie(
    claims: Annotated[JWTClaims, Depends(get_current_user_claims)],
) -> UUID:
    """Return the checked token subject as a UUID."""
    try:
        return UUID(claims.sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
        ) from exc

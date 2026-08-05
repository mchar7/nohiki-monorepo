"""FastAPI authentication dependencies for user-auth-service.

Provides cookie-based JWT validation using the service's own RS256 key,
so account-management endpoints can authenticate requests without an
external JWKS network call. Includes token blacklist checking.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from user_auth_service.core.config import get_settings
from user_auth_service.core.db import get_async_db
from user_auth_service.core.jwt_rs256 import JWT_ALGORITHM, get_jwt_handler
from user_auth_service.core.refresh_tokens import get_refresh_token_service
from user_auth_service.services.token_blacklist import get_token_blacklist


async def get_current_user_id_from_cookie(
    request: Request,
    db: Annotated[AsyncSession | None, Depends(get_async_db)] = None,
) -> UUID:
    """Extract and validate the user ID from the JWT access-token cookie."""
    settings = get_settings()
    token = request.cookies.get(settings.cookie.access_token_name)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        handler = get_jwt_handler()
        payload = pyjwt.decode(
            token,
            handler.public_key,
            algorithms=[JWT_ALGORITHM],
            audience=handler.config.audience,
            issuer=handler.config.issuer,
            options={"require": ["sub", "iat", "exp", "jti", "session_family_id"]},
        )
        user_id_str = str(payload["sub"])
        session_family_id = UUID(payload["session_family_id"])
        jti = payload["jti"]
        iat = payload["iat"]
    except (pyjwt.InvalidTokenError, KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    try:
        user_id = UUID(user_id_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
        ) from exc
    if not isinstance(jti, str) or not jti or not isinstance(iat, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    blacklist = get_token_blacklist(settings)
    if await blacklist.is_revoked(jti) or await blacklist.is_user_token_revoked(user_id_str, iat):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    if db is not None:
        try:
            family_revoked = await get_refresh_token_service().is_session_family_revoked(
                db,
                account_id=user_id,
                session_family_id=session_family_id,
            )
        except (SQLAlchemyError, OverflowError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication state unavailable",
            ) from exc
        if family_revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )

    return user_id

"""Authentication API routes.

This router handles:
- Account registration (creates account, sets auth cookies)
- Account login (sets auth cookies)
- Token refresh (rotates refresh token, sets new cookies)
- Logout (clears cookies, revokes session)
- JWKS endpoint (public key distribution)

IMPORTANT: This router does NOT include the /api/v1/auth/verify endpoint.
The forwardAuth pattern is removed in favor of cookie-based authentication
where each service verifies JWTs using the JWKS endpoint.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from nohiki_db_utils import OutboxWriter
from nohiki_fastapi_utils.rate_limiter import extract_client_ip
from nohiki_observability import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from user_auth_service.api.schemas import (
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    UserCreateResponse,
)
from user_auth_service.core.config import get_settings
from user_auth_service.core.cookies import (
    clear_auth_cookies,
    get_access_token_from_cookie,
    get_refresh_token_from_cookie,
    set_access_token_cookie,
    set_refresh_token_cookie,
)
from user_auth_service.core.db import get_async_db, get_outbox
from user_auth_service.core.jwt_rs256 import JWT_ALGORITHM, get_jwt_handler
from user_auth_service.core.refresh_tokens import RefreshTokenService, RevokedSession, get_refresh_token_service
from user_auth_service.db.models import Account
from user_auth_service.events.publishers import publish_access_token_revoked_event, publish_user_created_event
from user_auth_service.services import AuthRateLimiter, get_auth_rate_limiter, user_service
from user_auth_service.services.token_blacklist import get_token_blacklist

logger = get_logger(__name__)

router = APIRouter(tags=["auth"])


def _extract_client_ip(request: Request, trusted_proxy_cidrs: tuple[str, ...] | None = None) -> str:
    """Return the forwarded client only when the immediate peer is trusted."""
    configured_cidrs = get_settings().trusted_proxy_cidrs if trusted_proxy_cidrs is None else trusted_proxy_cidrs
    return extract_client_ip(request, configured_cidrs)


async def _check_register_rate_limit(
    request: Request,
) -> AuthRateLimiter:
    """Dependency that checks registration rate limit and returns the rate limiter."""
    settings = get_settings()
    rate_limiter = get_auth_rate_limiter(settings)
    client_ip = _extract_client_ip(request)
    await rate_limiter.check_register(client_ip)
    return rate_limiter


async def _check_login_rate_limit(
    request: Request,
    login_data: LoginRequest,
) -> AuthRateLimiter:
    """Dependency that checks login rate limit by email and IP."""
    settings = get_settings()
    rate_limiter = get_auth_rate_limiter(settings)
    client_ip = _extract_client_ip(request)
    await rate_limiter.check_login(login_data.email)
    await rate_limiter.check_login(client_ip)
    return rate_limiter


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserCreateResponse)
async def register(
    data: CreateUserRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    outbox: Annotated[OutboxWriter, Depends(get_outbox)],
    _rate_limiter: Annotated[AuthRateLimiter, Depends(_check_register_rate_limit)],
) -> UserCreateResponse:
    """Register a new user account.

    On success:
    - Creates user in database
    - Publishes user.created event
    - Sets __Host-nohiki_at (access token) cookie
    - Sets __Host-nohiki_rt (refresh token) cookie
    - Returns user metadata (does NOT return tokens in body)
    """
    user = await user_service.create_user(db, data)
    await publish_user_created_event(db, outbox, user)

    # Create session and tokens
    jwt_handler = get_jwt_handler()
    refresh_service = get_refresh_token_service()

    refresh_token, session_family_id = await refresh_service.create_session(db, user.id)
    access_token = jwt_handler.create_access_token(str(user.id), session_family_id=str(session_family_id))

    await db.commit()

    # Set cookies (tokens are NOT returned in response body)
    settings = get_settings()
    set_access_token_cookie(response, access_token, settings)
    set_refresh_token_cookie(response, refresh_token, settings)

    logger.info("Account registered and logged in", user_id=str(user.id))

    return UserCreateResponse(
        id=str(user.id),
        email=user.email,
        message="Account created successfully.",
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    rate_limiter: Annotated[AuthRateLimiter, Depends(_check_login_rate_limit)],
) -> LoginResponse:
    """Authenticate user and set auth cookies.

    On success:
    - Sets __Host-nohiki_at (access token) cookie
    - Sets __Host-nohiki_rt (refresh token) cookie
    - Returns user metadata (tokens are NOT in response body)
    """
    # Rate limiting already enforced by _check_login_rate_limit dependency.
    client_ip = _extract_client_ip(request)
    user = await user_service.authenticate_user(db, login_data.email, login_data.password.get_secret_value())
    if not user:
        # Record failed attempt
        await rate_limiter.record_failed_login(login_data.email)
        await rate_limiter.record_failed_login(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Clear failed attempts on success
    await rate_limiter.clear_failed_logins(login_data.email)
    await rate_limiter.clear_failed_logins(client_ip)

    # Create session and tokens
    settings = get_settings()
    jwt_handler = get_jwt_handler()
    refresh_service = get_refresh_token_service()

    refresh_token, session_family_id = await refresh_service.create_session(db, user.id)
    access_token = jwt_handler.create_access_token(str(user.id), session_family_id=str(session_family_id))

    await db.commit()

    # Set cookies (tokens are HttpOnly, not in response body)
    set_access_token_cookie(response, access_token, settings)
    set_refresh_token_cookie(response, refresh_token, settings)

    logger.info("Account logged in", user_id=str(user.id))

    return LoginResponse(
        user_id=str(user.id),
        email=user.email,
        display_name=user.display_name,
    )


@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    outbox: Annotated[OutboxWriter, Depends(get_outbox)],
) -> dict[str, str]:
    """Refresh the access token using the refresh token cookie.

    This endpoint:
    - Validates the refresh token from cookie
    - Rotates the refresh token (old token becomes invalid)
    - Sets new __Host-nohiki_at and __Host-nohiki_rt cookies

    If the same refresh token is used twice (reuse detection),
    the entire session family is revoked for security.
    """
    settings = get_settings()
    old_refresh_token = get_refresh_token_from_cookie(request.cookies, settings)
    if not old_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )

    refresh_service = get_refresh_token_service()
    result = await refresh_service.rotate_token(db, old_refresh_token)

    if isinstance(result, RevokedSession):
        family_horizon = datetime.now(UTC) + timedelta(minutes=get_jwt_handler().config.access_token_expire_minutes)
        await publish_access_token_revoked_event(
            db,
            outbox,
            user_id=result.account_id,
            jti=None,
            expires_at=family_horizon,
            session_family_id=result.session_family_id,
        )
        await db.commit()
        clear_auth_cookies(response, settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if result is None:
        # Persist reuse-detection revocation before raising; otherwise the
        # request-scoped session rolls it back with the HTTP error.
        await db.commit()
        # Token invalid, expired, or reuse detected
        clear_auth_cookies(response, settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    new_refresh_token, user_id, session_family_id = result
    account = await db.get(Account, user_id)
    if account is None or not account.is_active:
        await refresh_service.revoke_session(db, new_refresh_token)
        await db.commit()
        clear_auth_cookies(response, settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive",
        )

    jwt_handler = get_jwt_handler()
    new_access_token = jwt_handler.create_access_token(str(user_id), session_family_id=str(session_family_id))

    await db.commit()

    # Set new cookies
    set_access_token_cookie(response, new_access_token, settings)
    set_refresh_token_cookie(response, new_refresh_token, settings)

    logger.debug("Token refreshed", user_id=str(user_id))

    return {"status": "refreshed", "user_id": str(user_id)}


def _extract_access_token_claims(request: Request) -> tuple[UUID, UUID, datetime, UUID | None] | None:
    """Verify and extract the revocation-relevant claims from the access cookie."""
    settings = get_settings()
    access_token = get_access_token_from_cookie(request.cookies, settings)
    if not access_token:
        return None

    try:
        handler = get_jwt_handler()
        payload = pyjwt.decode(
            access_token,
            handler.public_key,
            algorithms=[JWT_ALGORITHM],
            audience=handler.config.audience,
            issuer=handler.config.issuer,
            options={"require": ["sub", "jti", "exp"]},
        )
        user_id = UUID(payload["sub"])
        jti = UUID(payload["jti"])
        expires_at = datetime.fromtimestamp(payload["exp"], UTC)
        raw_family_id = payload.get("session_family_id")
        session_family_id = UUID(raw_family_id) if raw_family_id is not None else None
    except pyjwt.InvalidTokenError, KeyError, TypeError, ValueError, OverflowError, OSError:
        return None

    return user_id, jti, expires_at, session_family_id


async def _blacklist_access_token(jti: UUID, expires_at: datetime) -> None:
    """Blacklist a verified access-token JTI for its remaining lifetime."""
    remaining = int(expires_at.timestamp() - datetime.now(UTC).timestamp())
    if remaining > 0:
        blacklist = get_token_blacklist(get_settings())
        await blacklist.revoke(str(jti), expires_in=remaining)


async def _revoke_access_claimed_family(
    db: AsyncSession,
    refresh_service: RefreshTokenService,
    user_id: UUID,
    session_family_id: UUID | None,
) -> RevokedSession | None:
    """Revoke the family identified by a verified access token claim."""
    if session_family_id is None:
        return None
    revoke_family = getattr(refresh_service, "revoke_session_family", None)
    if not inspect.iscoroutinefunction(revoke_family):
        return None
    return await revoke_family(db, account_id=user_id, session_family_id=session_family_id)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    outbox: Annotated[OutboxWriter, Depends(get_outbox)],
) -> dict[str, str]:
    """Logout the user.

    This endpoint:
    - Revokes the session (all tokens in session family)
    - Clears auth cookies
    """
    settings = get_settings()
    refresh_token = get_refresh_token_from_cookie(request.cookies, settings)
    access_claims = _extract_access_token_claims(request)
    refresh_service = get_refresh_token_service()
    revoked_sessions: list[RevokedSession] = []
    if refresh_token:
        revoked_session = await refresh_service.revoke_session(db, refresh_token)
        if revoked_session is not None:
            revoked_sessions.append(revoked_session)

    if access_claims is not None:
        user_id, jti, token_expires_at, session_family_id = access_claims
        claimed_session = await _revoke_access_claimed_family(
            db,
            refresh_service,
            user_id=user_id,
            session_family_id=session_family_id,
        )
        if claimed_session is not None:
            revoked_sessions.append(claimed_session)
        family_horizon = (
            datetime.now(UTC) + timedelta(minutes=get_jwt_handler().config.access_token_expire_minutes)
            if session_family_id is not None or revoked_sessions
            else None
        )
        expires_at = (
            max(token_expires_at, family_horizon)
            if session_family_id is not None and family_horizon is not None
            else token_expires_at
        )
        await publish_access_token_revoked_event(
            db,
            outbox,
            user_id=user_id,
            jti=jti,
            expires_at=expires_at,
            session_family_id=session_family_id,
        )
    else:
        family_horizon = (
            datetime.now(UTC) + timedelta(minutes=get_jwt_handler().config.access_token_expire_minutes)
            if revoked_sessions
            else None
        )

    for revoked_session in revoked_sessions:
        same_as_access = (
            access_claims is not None
            and revoked_session.account_id == access_claims[0]
            and revoked_session.session_family_id == access_claims[3]
        )
        if not same_as_access and family_horizon is not None:
            await publish_access_token_revoked_event(
                db,
                outbox,
                user_id=revoked_session.account_id,
                jti=None,
                expires_at=family_horizon,
                session_family_id=revoked_session.session_family_id,
            )

    if access_claims is not None or revoked_sessions:
        await db.commit()

    if access_claims is not None:
        await _blacklist_access_token(jti, expires_at)

    clear_auth_cookies(response, settings)

    logger.info("Account logged out")

    return {"status": "logged_out"}


# JWKS Endpoint (public, no auth required)


@router.get("/.well-known/jwks.json", include_in_schema=False)
async def get_jwks() -> dict[str, Any]:
    """Public JWKS endpoint for JWT verification.

    This endpoint is served at /.well-known/jwks.json
    and provides the public keys needed to verify JWTs.

    Response headers include caching directives:
    - Cache-Control: public, max-age=3600

    Note: This route is registered separately at the app level
    to serve from /.well-known/jwks.json
    """
    jwt_handler = get_jwt_handler()
    return jwt_handler.get_jwks()

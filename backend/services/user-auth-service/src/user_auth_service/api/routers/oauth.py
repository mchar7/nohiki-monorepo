"""OAuth authentication API endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from nohiki_observability import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from user_auth_service.api.schemas.oauth import (
    OAuthErrorCode,
    OAuthProvider,
    OAuthProviderInfo,
    OAuthProvidersResponse,
)
from user_auth_service.core.config import get_settings
from user_auth_service.core.cookies import (
    clear_excess_oauth_state_cookies,
    clear_oauth_state_cookie,
    get_oauth_state_from_cookie,
    set_access_token_cookie,
    set_oauth_state_cookie,
    set_refresh_token_cookie,
)
from user_auth_service.core.db import get_async_db
from user_auth_service.core.deps import get_oauth_service_dep
from user_auth_service.core.jwt_rs256 import RS256JWTHandler, get_jwt_handler
from user_auth_service.core.oauth_state import OAuthState
from user_auth_service.core.refresh_tokens import RefreshTokenService, get_refresh_token_service
from user_auth_service.services.oauth_service import OAuthError, OAuthResult, OAuthService

logger = get_logger(__name__)

router = APIRouter(tags=["OAuth"])

PROVIDER_DISPLAY_NAMES: dict[OAuthProvider, str] = {
    OAuthProvider.GITHUB: "GitHub",
    OAuthProvider.GOOGLE: "Google",
}

ERROR_CODE_MAPPING: dict[str, OAuthErrorCode] = {
    "state_mismatch": OAuthErrorCode.STATE_MISMATCH,
    "token_exchange_failed": OAuthErrorCode.CODE_EXCHANGE_FAILED,
    "profile_fetch_failed": OAuthErrorCode.PROFILE_FETCH_FAILED,
    "account_disabled": OAuthErrorCode.ACCOUNT_DISABLED,
    "access_denied": OAuthErrorCode.ACCESS_DENIED,
}


def _build_error_redirect(error: OAuthErrorCode, provider: str) -> str:
    """Build error redirect URL with query params."""
    settings = get_settings()
    return f"{settings.oauth.error_redirect_url}?{urlencode({'error': error.value, 'provider': provider})}"


def _build_success_redirect(return_url: str) -> str:
    """Build success redirect URL using the backend-validated return path."""
    settings = get_settings()
    return f"{settings.oauth.success_redirect_url}?{urlencode({'success': 'true', 'returnUrl': return_url})}"


def _map_error_code(internal_code: str) -> OAuthErrorCode:
    """Map internal OAuth error code to API error code."""
    return ERROR_CODE_MAPPING.get(internal_code, OAuthErrorCode.SERVER_ERROR)


@dataclass(frozen=True, slots=True)
class OAuthSessionParams:
    """Inputs required to create an authenticated OAuth session response."""

    result: OAuthResult
    provider: str
    return_url: str
    db: AsyncSession
    jwt_handler: RS256JWTHandler
    refresh_service: RefreshTokenService


async def _create_session_and_response(params: OAuthSessionParams) -> RedirectResponse:
    """Create session tokens and build success response."""
    settings = get_settings()
    refresh_token, session_family_id = await params.refresh_service.create_session(
        db=params.db,
        account_id=params.result.account.id,
    )
    access_token = params.jwt_handler.create_access_token(
        user_id=str(params.result.account.id), session_family_id=str(session_family_id)
    )
    await params.db.commit()

    response = RedirectResponse(url=_build_success_redirect(params.return_url), status_code=302)
    set_access_token_cookie(response, access_token, settings)
    set_refresh_token_cookie(response, refresh_token, settings)

    logger.info(
        "OAuth login successful",
        provider=params.provider,
        account_id=str(params.result.account.id),
        is_new_account=params.result.is_new_account,
        is_new_link=params.result.is_new_link,
    )
    return response


@dataclass(slots=True)
class OAuthCallbackDeps:
    """Bundled dependencies for OAuth callback endpoint."""

    oauth_service: OAuthService
    db: AsyncSession
    jwt_handler: RS256JWTHandler
    refresh_service: RefreshTokenService


@dataclass(frozen=True, slots=True)
class OAuthCallbackQuery:
    """Query parameters received by an OAuth callback."""

    code: str | None = None
    state: str | None = None
    error: str | None = None


def get_oauth_callback_query(
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> OAuthCallbackQuery:
    """Bundle callback query parameters for dependency injection."""
    return OAuthCallbackQuery(code=code, state=state, error=error)


def get_oauth_callback_deps(
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service_dep)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    jwt_handler: Annotated[RS256JWTHandler, Depends(get_jwt_handler)],
    refresh_service: Annotated[RefreshTokenService, Depends(get_refresh_token_service)],
) -> OAuthCallbackDeps:
    """Dependency that bundles all OAuth callback dependencies."""
    return OAuthCallbackDeps(
        oauth_service=oauth_service,
        db=db,
        jwt_handler=jwt_handler,
        refresh_service=refresh_service,
    )


type OAuthCallbackOutcome = OAuthResult | OAuthErrorCode


async def _handle_callback_result(
    deps: OAuthCallbackDeps,
    provider: str,
    code: str,
    consumed_state: OAuthState,
) -> OAuthCallbackOutcome:
    """Handle provider callback, converting failures to API error codes."""
    try:
        return await deps.oauth_service.handle_callback(
            db=deps.db,
            provider=provider,
            code=code,
            state=consumed_state,
        )
    except OAuthError as exc:
        await deps.db.rollback()
        logger.warning(
            "OAuth callback failed",
            provider=provider,
            error_code=exc.code,
            error_description=exc.description,
        )
        return _map_error_code(exc.code)
    except Exception:
        await deps.db.rollback()
        logger.exception("Unexpected error during OAuth callback", provider=provider)
        return OAuthErrorCode.SERVER_ERROR


@router.get(
    "/providers",
    response_model=OAuthProvidersResponse,
    summary="List available OAuth providers",
)
async def get_providers() -> OAuthProvidersResponse:
    """Get list of enabled OAuth providers."""
    settings = get_settings()
    providers: list[OAuthProviderInfo] = []

    for provider in OAuthProvider:
        provider_settings = settings.oauth.get_provider(provider.value)
        is_enabled = provider_settings is not None and provider_settings.enabled and provider_settings.is_configured()
        providers.append(
            OAuthProviderInfo(
                id=provider,
                name=PROVIDER_DISPLAY_NAMES.get(provider, provider.value),
                enabled=is_enabled,
            )
        )

    return OAuthProvidersResponse(providers=providers)


@router.get(
    "/{provider}/authorize",
    response_class=RedirectResponse,
    status_code=302,
    summary="Start OAuth authorization flow",
)
async def authorize(
    provider: OAuthProvider,
    request: Request,
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service_dep)],
    return_url: Annotated[str, Query(alias="returnUrl", max_length=2048)] = "/",
) -> RedirectResponse:
    """Redirect to OAuth provider's authorization page."""
    try:
        auth_url, state = await oauth_service.start_authorization(provider.value, return_url)
    except OAuthError:
        logger.exception("Failed to start OAuth authorization", provider=provider.value)
        error_url = _build_error_redirect(OAuthErrorCode.SERVER_ERROR, provider.value)
        return RedirectResponse(url=error_url, status_code=302)
    response = RedirectResponse(url=auth_url, status_code=302)
    clear_excess_oauth_state_cookies(response, request.cookies, get_settings())
    set_oauth_state_cookie(response, state, get_settings())
    return response


@router.get(
    "/{provider}/callback",
    response_class=RedirectResponse,
    status_code=302,
    summary="Handle OAuth callback",
)
async def callback(
    request: Request,
    provider: OAuthProvider,
    deps: Annotated[OAuthCallbackDeps, Depends(get_oauth_callback_deps)],
    query: Annotated[OAuthCallbackQuery, Depends(get_oauth_callback_query)],
) -> RedirectResponse:
    """Handle OAuth provider callback and create session."""
    settings = get_settings()

    def redirect(error_code: OAuthErrorCode, callback_state: str | None = query.state) -> RedirectResponse:
        response = RedirectResponse(
            url=_build_error_redirect(error_code, provider.value),
            status_code=302,
        )
        if callback_state is not None:
            clear_oauth_state_cookie(response, callback_state, settings)
        return response

    if not query.state:
        return redirect(OAuthErrorCode.STATE_MISMATCH)

    cookie_state = get_oauth_state_from_cookie(request.cookies, query.state, settings)
    try:
        consumed_state = await deps.oauth_service.consume_callback_state(
            provider.value,
            query.state,
            cookie_state,
        )
    except OAuthError as exc:
        logger.warning(
            "OAuth callback state validation failed",
            provider=provider.value,
            error_code=exc.code,
        )
        return redirect(_map_error_code(exc.code))

    if query.error or not query.code:
        error_code = OAuthErrorCode.ACCESS_DENIED if query.error == "access_denied" else OAuthErrorCode.SERVER_ERROR
        if not query.error:
            error_code = OAuthErrorCode.STATE_MISMATCH
        return redirect(error_code)

    outcome = await _handle_callback_result(deps, provider.value, query.code, consumed_state)
    if isinstance(outcome, OAuthErrorCode):
        return redirect(outcome)

    if not outcome.account.is_active:
        return redirect(OAuthErrorCode.ACCOUNT_DISABLED)

    response = await _create_session_and_response(
        OAuthSessionParams(
            result=outcome,
            provider=provider.value,
            return_url=consumed_state.return_url,
            db=deps.db,
            jwt_handler=deps.jwt_handler,
            refresh_service=deps.refresh_service,
        )
    )
    clear_oauth_state_cookie(response, query.state, settings)
    return response

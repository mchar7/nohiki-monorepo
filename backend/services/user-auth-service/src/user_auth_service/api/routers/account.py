"""Account management API routes.

All endpoints authenticate via the JWT access-token cookie issued by this
service.  The service self-validates using its own RSA public key so no
external JWKS call is required.
"""

from __future__ import annotations

import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from nohiki_db_utils import OutboxWriter
from sqlalchemy.ext.asyncio import AsyncSession

from user_auth_service.api.schemas import UpdateUserRequest, UserResponse
from user_auth_service.api.schemas.oauth import (
    OAuthIdentitiesResponse,
    OAuthIdentityResponse,
    OAuthProvider,
)
from user_auth_service.core.auth_deps import get_current_user_id_from_cookie
from user_auth_service.core.config import get_settings
from user_auth_service.core.cookies import clear_auth_cookies
from user_auth_service.core.db import get_async_db, get_outbox
from user_auth_service.core.deps import get_oauth_service_dep
from user_auth_service.db.models import Account
from user_auth_service.events.publishers import publish_user_deleted_event, publish_user_updated_event
from user_auth_service.services import user_service
from user_auth_service.services.oauth_service import OAuthError, OAuthService
from user_auth_service.services.token_blacklist import get_token_blacklist

router = APIRouter(tags=["account"])


async def get_current_active_user_id(
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> UUID:
    """Require the token subject to remain an active local account."""
    account = await db.get(Account, user_id)
    if account is None or not account.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is inactive")
    return user_id


@router.get("", response_model=UserResponse)
async def get_account(
    db: Annotated[AsyncSession, Depends(get_async_db)],
    user_id: Annotated[UUID, Depends(get_current_active_user_id)],
) -> UserResponse:
    """Get current user's account information."""
    user = await user_service.get_user_by_id(db, user_id)
    return UserResponse.model_validate(user)


@router.patch("", response_model=UserResponse)
async def update_account(
    user_update: UpdateUserRequest,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    user_id: Annotated[UUID, Depends(get_current_active_user_id)],
    outbox: Annotated[OutboxWriter, Depends(get_outbox)],
) -> UserResponse:
    """Update current user's account information."""
    user = await user_service.update_user(db, user_id, user_update)
    await publish_user_updated_event(db, outbox, user)
    await db.commit()
    return UserResponse.model_validate(user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    user_id: Annotated[UUID, Depends(get_current_active_user_id)],
    outbox: Annotated[OutboxWriter, Depends(get_outbox)],
) -> None:
    """Delete current user's account, revoke all tokens, and clear cookies."""
    await user_service.delete_user(db, user_id)
    await publish_user_deleted_event(db, outbox, user_id)
    await db.commit()

    # Revoke all outstanding tokens for the deleted user
    settings = get_settings()
    blacklist = get_token_blacklist(settings)
    await blacklist.revoke_all_for_user(str(user_id), int(time.time()))

    clear_auth_cookies(response, settings)


@router.get("/oauth-identities", response_model=OAuthIdentitiesResponse)
async def get_oauth_identities(
    account_id: Annotated[UUID, Depends(get_current_active_user_id)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service_dep)],
) -> OAuthIdentitiesResponse:
    """Get all OAuth identities linked to current account."""
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    identities = await oauth_service.get_linked_identities(db, account_id)

    return OAuthIdentitiesResponse(
        identities=[
            OAuthIdentityResponse(
                provider=OAuthProvider(identity.provider),
                provider_username=identity.provider_username,
                provider_email=identity.provider_email,
                linked_at=identity.created_at.isoformat(),
            )
            for identity in identities
        ],
        has_password=account.has_password,
    )


@router.delete("/oauth/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_oauth_provider(
    provider: OAuthProvider,
    account_id: Annotated[UUID, Depends(get_current_active_user_id)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service_dep)],
) -> None:
    """Unlink an OAuth provider from current account."""
    try:
        unlinked = await oauth_service.unlink_identity(
            db=db,
            account_id=account_id,
            provider=provider.value,
        )
        if not unlinked:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity not found")
        await db.commit()
    except OAuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.description) from e

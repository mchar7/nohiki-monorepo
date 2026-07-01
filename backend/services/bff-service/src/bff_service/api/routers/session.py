"""Session API routes - current user info from JWT claims."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from nohiki_fastapi_utils import JWTClaims
from nohiki_observability import get_logger
from pydantic import BaseModel

from bff_service.api.deps.auth import get_current_user_claims

logger = get_logger(__name__)

router = APIRouter()


class SessionResponse(BaseModel):
    """Response for session endpoint."""

    user_id: str
    roles: list[str]
    permissions: list[str]
    tenant_id: str | None = None


@router.get("", response_model=SessionResponse)
async def get_session(
    claims: Annotated[JWTClaims, Depends(get_current_user_claims)],
) -> SessionResponse:
    """Get current session info from JWT claims.

    This endpoint returns user metadata from the access token.
    Used by the frontend to check authentication status.
    """
    logger.debug("Session requested", user_id=claims.sub)

    return SessionResponse(
        user_id=claims.sub,
        roles=claims.roles,
        permissions=claims.permissions,
        tenant_id=claims.tenant_id,
    )

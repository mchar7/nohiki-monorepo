import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from nohiki_fastapi_utils import JWTClaims


@pytest.mark.asyncio
async def test_get_session_returns_jwt_claims() -> None:
    from bff_service.api.routers.session import get_session

    claims = JWTClaims(
        sub="user-123",
        iss="https://api.nohiki.com",
        aud="https://app.nohiki.com",
        exp=9999999999,
        iat=0,
        jti="test-jti-1",
        roles=["user", "admin"],
        permissions=["read:profiles", "write:profiles"],
        tenant_id="tenant-456",
    )

    result = await get_session(claims)

    assert result.user_id == "user-123"
    assert result.roles == ["user", "admin"]
    assert result.permissions == ["read:profiles", "write:profiles"]
    assert result.tenant_id == "tenant-456"


@pytest.mark.asyncio
async def test_get_session_handles_none_tenant_id() -> None:
    from bff_service.api.routers.session import get_session

    claims = JWTClaims(
        sub="user-789",
        iss="https://api.nohiki.com",
        aud="https://app.nohiki.com",
        exp=9999999999,
        iat=0,
        jti="test-jti-2",
        roles=["user"],
        permissions=["read:profiles"],
        tenant_id=None,
    )

    result = await get_session(claims)

    assert result.user_id == "user-789"
    assert result.tenant_id is None


@pytest.mark.asyncio
async def test_get_session_handles_empty_roles_and_permissions() -> None:
    from bff_service.api.routers.session import get_session

    claims = JWTClaims(
        sub="user-abc",
        iss="https://api.nohiki.com",
        aud="https://app.nohiki.com",
        exp=9999999999,
        iat=0,
        jti="test-jti-3",
        roles=[],
        permissions=[],
        tenant_id=None,
    )

    result = await get_session(claims)

    assert result.user_id == "user-abc"
    assert result.roles == []
    assert result.permissions == []


def test_session_rejects_revoked_auth() -> None:
    from bff_service.api.deps.auth import get_current_user_claims
    from bff_service.api.routers.session import router

    async def reject_revoked_token() -> None:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/session")
    app.dependency_overrides[get_current_user_claims] = reject_revoked_token

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/session")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired access token"}

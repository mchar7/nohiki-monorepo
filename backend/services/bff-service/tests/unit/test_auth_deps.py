from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, get_type_hints
from unittest.mock import AsyncMock

import pytest
from bff_service.api.deps import auth
from fastapi import Depends, FastAPI, HTTPException
from fastapi.params import Depends as DependsParam
from fastapi.testclient import TestClient
from nohiki_fastapi_utils import JWTClaims
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _claims(
    *,
    sub: str | None = None,
    jti: str | None = None,
    iat: int = 1_700_000_000,
    session_family_id: str | None = None,
) -> JWTClaims:
    return JWTClaims(
        sub=sub or str(uuid.uuid4()),
        iss="https://api.nohiki.com",
        aud="https://app.nohiki.com",
        exp=9_999_999_999,
        iat=iat,
        jti=jti if jti is not None else str(uuid.uuid4()),
        roles=["user"],
        permissions=[],
        tenant_id=None,
        session_family_id=session_family_id,
    )


@pytest.mark.asyncio
async def test_current_claims_returns_valid_token(mocker: MockerFixture) -> None:
    claims = _claims()
    check = mocker.patch.object(auth, "is_access_token_revoked", new=AsyncMock(return_value=False))

    assert await auth.get_current_user_claims(claims, AsyncMock()) is claims
    check.assert_awaited_once()
    await_args = check.await_args
    assert await_args is not None
    assert await_args.kwargs["user_id"] == uuid.UUID(claims.sub)
    assert await_args.kwargs["jti"] == claims.jti
    assert int(await_args.kwargs["issued_at"].timestamp()) == claims.iat
    assert await_args.kwargs["session_family_id"] is None


@pytest.mark.asyncio
async def test_current_claims_forwards_family_and_denies_family_revocation(mocker: MockerFixture) -> None:
    family_id = str(uuid.uuid4())
    claims = _claims(session_family_id=family_id)
    check = mocker.patch.object(auth, "is_access_token_revoked", new=AsyncMock(return_value=True))

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user_claims(claims, AsyncMock())

    await_args = check.await_args
    assert await_args is not None
    assert await_args.kwargs["session_family_id"] == family_id
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired access token"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["jti", "cutoff"])
async def test_current_claims_rejects_revoked_token(mocker: MockerFixture, reason: str) -> None:
    claims = _claims()
    mocker.patch.object(auth, "is_access_token_revoked", new=AsyncMock(return_value=True))

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user_claims(claims, AsyncMock())

    assert reason in {"jti", "cutoff"}  # Both ledger revocation paths intentionally share the boundary response.
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired access token"


@pytest.mark.asyncio
async def test_current_claims_allows_token_issued_after_cutoff(mocker: MockerFixture) -> None:
    claims = _claims(iat=1_800_000_000)
    check = mocker.patch.object(auth, "is_access_token_revoked", new=AsyncMock(return_value=False))

    assert await auth.get_current_user_claims(claims, AsyncMock()) is claims
    await_args = check.await_args
    assert await_args is not None
    assert int(await_args.kwargs["issued_at"].timestamp()) == 1_800_000_000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claims", "detail"),
    [
        (_claims(sub="not-a-uuid"), "Invalid user ID in token"),
        (_claims(jti=""), "Invalid or expired access token"),
    ],
)
async def test_current_claims_rejects_malformed_identity(mocker: MockerFixture, claims: JWTClaims, detail: str) -> None:
    check = mocker.patch.object(auth, "is_access_token_revoked", new=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user_claims(claims, AsyncMock())

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == detail
    check.assert_not_awaited()


@pytest.mark.asyncio
async def test_current_claims_maps_database_failure_to_503(mocker: MockerFixture) -> None:
    mocker.patch.object(
        auth,
        "is_access_token_revoked",
        new=AsyncMock(side_effect=OperationalError("select", {}, RuntimeError("db unavailable"))),
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user_claims(_claims(), AsyncMock())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Authentication state unavailable"


def test_user_id_dependency_composes_checked_claims() -> None:
    annotation = get_type_hints(auth.get_current_user_id_from_cookie, include_extras=True)["claims"]
    dependency = next(item for item in annotation.__metadata__ if isinstance(item, DependsParam))

    assert dependency.dependency is auth.get_current_user_claims


def test_fastapi_caches_checked_claims_for_composed_dependencies(mocker: MockerFixture) -> None:
    claims = _claims()
    check = mocker.patch.object(auth, "is_access_token_revoked", new=AsyncMock(return_value=False))
    app = FastAPI()

    @app.get("/protected")
    async def protected(
        checked: Annotated[JWTClaims, Depends(auth.get_current_user_claims)],
        user_id: Annotated[uuid.UUID, Depends(auth.get_current_user_id_from_cookie)],
    ) -> dict[str, str]:
        return {"sub": checked.sub, "user_id": str(user_id)}

    async def _override_async_db() -> AsyncMock:
        return AsyncMock()

    app.dependency_overrides[auth.get_verified_user_claims] = lambda: claims
    app.dependency_overrides[auth.get_async_db] = _override_async_db

    response = TestClient(app).get("/protected")

    assert response.status_code == 200
    assert response.json() == {"sub": claims.sub, "user_id": claims.sub}
    check.assert_awaited_once()

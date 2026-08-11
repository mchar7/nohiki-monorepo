"""Unit tests for user_auth_service.core.auth_deps module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from user_auth_service.core.auth_deps import get_current_user_id_from_cookie
from user_auth_service.core.jwt_rs256 import JWTConfig, RS256JWTHandler, generate_rsa_keypair


@pytest.fixture(scope="module")
def private_key_pem() -> str:
    """Create one signing key for malformed-claim token cases."""
    private_pem, _ = generate_rsa_keypair()
    return private_pem


@pytest.fixture
def jwt_handler(private_key_pem: str) -> RS256JWTHandler:
    """Create a JWT handler using the test signing key."""
    config = JWTConfig(
        issuer="http://localhost:8000",
        audience="nohiki-api",
        key_id="test-key",
        access_token_expire_minutes=15,
    )
    return RS256JWTHandler(private_key_pem, config)


def _mock_blacklist() -> MagicMock:
    """Create a mock token blacklist that allows all tokens."""
    blacklist = MagicMock()
    blacklist.is_revoked = AsyncMock(return_value=False)
    blacklist.is_user_token_revoked = AsyncMock(return_value=False)
    return blacklist


def _mock_refresh_service() -> MagicMock:
    """Create a mock refresh-token service reporting no revoked session family."""
    return MagicMock(is_session_family_revoked=AsyncMock(return_value=False))


class TestGetCurrentUserIdFromCookie:
    """Tests for get_current_user_id_from_cookie dependency."""

    @pytest.mark.asyncio
    async def test_returns_uuid_for_valid_token(self, jwt_handler: RS256JWTHandler) -> None:
        """Returns a UUID when the cookie holds a valid access token."""
        user_id = str(uuid.uuid4())
        token = jwt_handler.create_access_token(user_id, session_family_id=str(uuid.uuid4()))

        mock_request = MagicMock()
        mock_request.cookies = {"nohiki_at": token}

        with (
            patch(
                "user_auth_service.core.auth_deps.get_settings",
                return_value=MagicMock(cookie=MagicMock(access_token_name="nohiki_at")),
            ),
            patch(
                "user_auth_service.core.auth_deps.get_jwt_handler",
                return_value=jwt_handler,
            ),
            patch(
                "user_auth_service.core.auth_deps.get_token_blacklist",
                return_value=_mock_blacklist(),
            ),
            patch(
                "user_auth_service.core.auth_deps.get_refresh_token_service",
                return_value=_mock_refresh_service(),
            ),
        ):
            result = await get_current_user_id_from_cookie(mock_request, MagicMock())
        assert str(result) == user_id

    @pytest.mark.asyncio
    async def test_rejects_locally_revoked_family_before_account_mutation(
        self,
        jwt_handler: RS256JWTHandler,
    ) -> None:
        """A persisted family revocation rejects account-authenticated requests locally."""
        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        token = jwt_handler.create_access_token(str(user_id), session_family_id=str(family_id))
        mock_request = MagicMock()
        mock_request.cookies = {"nohiki_at": token}
        blacklist = _mock_blacklist()
        family_check = AsyncMock(return_value=True)
        service = MagicMock(is_session_family_revoked=family_check)
        db = MagicMock()

        with (
            patch(
                "user_auth_service.core.auth_deps.get_settings",
                return_value=MagicMock(cookie=MagicMock(access_token_name="nohiki_at")),
            ),
            patch("user_auth_service.core.auth_deps.get_jwt_handler", return_value=jwt_handler),
            patch("user_auth_service.core.auth_deps.get_token_blacklist", return_value=blacklist),
            patch("user_auth_service.core.auth_deps.get_refresh_token_service", return_value=service),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user_id_from_cookie(mock_request, db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token has been revoked"
        family_check.assert_awaited_once_with(
            db,
            account_id=user_id,
            session_family_id=family_id,
        )

    @pytest.mark.asyncio
    async def test_maps_family_state_database_failure_to_503(
        self,
        jwt_handler: RS256JWTHandler,
    ) -> None:
        """Unavailable local family state fails closed with a service-unavailable response."""
        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        token = jwt_handler.create_access_token(str(user_id), session_family_id=str(family_id))
        mock_request = MagicMock()
        mock_request.cookies = {"nohiki_at": token}
        service = MagicMock(
            is_session_family_revoked=AsyncMock(
                side_effect=OperationalError("select", {}, RuntimeError("database down"))
            )
        )

        with (
            patch(
                "user_auth_service.core.auth_deps.get_settings",
                return_value=MagicMock(cookie=MagicMock(access_token_name="nohiki_at")),
            ),
            patch("user_auth_service.core.auth_deps.get_jwt_handler", return_value=jwt_handler),
            patch("user_auth_service.core.auth_deps.get_token_blacklist", return_value=_mock_blacklist()),
            patch("user_auth_service.core.auth_deps.get_refresh_token_service", return_value=service),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user_id_from_cookie(mock_request, MagicMock())

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Authentication state unavailable"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing_claim", ["sub", "iat", "exp", "jti", "session_family_id"])
    async def test_raises_401_when_required_claim_is_missing(
        self,
        jwt_handler: RS256JWTHandler,
        private_key_pem: str,
        missing_claim: str,
    ) -> None:
        """Every security-critical access-token claim is required at authentication."""
        now = datetime.now(UTC)
        payload = {
            "sub": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": str(uuid.uuid4()),
            "session_family_id": str(uuid.uuid4()),
            "aud": jwt_handler.config.audience,
            "iss": jwt_handler.config.issuer,
        }
        del payload[missing_claim]
        token = jwt.encode(payload, private_key_pem, algorithm="RS256")
        mock_request = MagicMock()
        mock_request.cookies = {"nohiki_at": token}
        blacklist = _mock_blacklist()

        with (
            patch(
                "user_auth_service.core.auth_deps.get_settings",
                return_value=MagicMock(cookie=MagicMock(access_token_name="nohiki_at")),
            ),
            patch("user_auth_service.core.auth_deps.get_jwt_handler", return_value=jwt_handler),
            patch("user_auth_service.core.auth_deps.get_token_blacklist", return_value=blacklist),
            patch(
                "user_auth_service.core.auth_deps.get_refresh_token_service",
                return_value=_mock_refresh_service(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user_id_from_cookie(mock_request, MagicMock())

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired token"
        blacklist.is_revoked.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_401_when_cookie_absent(self) -> None:
        """Raises 401 when the access-token cookie is not present."""
        mock_request = MagicMock()
        mock_request.cookies = {}

        with (
            patch(
                "user_auth_service.core.auth_deps.get_settings",
                return_value=MagicMock(cookie=MagicMock(access_token_name="nohiki_at")),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user_id_from_cookie(mock_request, MagicMock())

        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_raises_401_for_invalid_token(self) -> None:
        """Raises 401 when the token fails signature verification."""
        mock_request = MagicMock()
        mock_request.cookies = {"nohiki_at": "not.a.valid.jwt"}

        mock_handler = MagicMock()
        mock_handler.public_key = MagicMock()
        mock_handler.config = MagicMock(audience="nohiki-api", issuer="http://localhost:8000")

        with (
            patch(
                "user_auth_service.core.auth_deps.get_settings",
                return_value=MagicMock(cookie=MagicMock(access_token_name="nohiki_at")),
            ),
            patch(
                "user_auth_service.core.auth_deps.get_jwt_handler",
                return_value=mock_handler,
            ),
            patch(
                "user_auth_service.core.auth_deps.pyjwt.decode",
                side_effect=jwt.InvalidTokenError("bad token"),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user_id_from_cookie(mock_request, MagicMock())

        assert exc_info.value.status_code == 401
        assert "Invalid or expired token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_raises_401_for_invalid_uuid_in_sub(self) -> None:
        """Raises 401 when the sub claim is not a valid UUID."""
        mock_request = MagicMock()
        mock_request.cookies = {"nohiki_at": "some.token.value"}

        mock_handler = MagicMock()
        mock_handler.public_key = MagicMock()
        mock_handler.config = MagicMock(audience="nohiki-api", issuer="http://localhost:8000")

        with (
            patch(
                "user_auth_service.core.auth_deps.get_settings",
                return_value=MagicMock(cookie=MagicMock(access_token_name="nohiki_at")),
            ),
            patch(
                "user_auth_service.core.auth_deps.get_jwt_handler",
                return_value=mock_handler,
            ),
            patch(
                "user_auth_service.core.auth_deps.pyjwt.decode",
                return_value={
                    "sub": "not-a-uuid",
                    "jti": None,
                    "iat": None,
                    "session_family_id": str(uuid.uuid4()),
                },
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user_id_from_cookie(mock_request, MagicMock())

        assert exc_info.value.status_code == 401
        assert "Invalid user ID" in exc_info.value.detail

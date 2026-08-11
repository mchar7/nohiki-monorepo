"""Unit tests for user_auth_service.api.routers.auth module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID

import pytest
from fastapi import HTTPException, Request, Response
from nohiki_db_utils import OutboxWriter
from nohiki_db_utils.testing import create_mock_session
from pydantic import SecretStr
from user_auth_service.api.routers.auth import (
    _check_login_rate_limit,
    _check_register_rate_limit,
    _extract_client_ip,
    get_jwks,
    get_outbox,
    login,
    logout,
    refresh_token,
    register,
)
from user_auth_service.api.schemas import CreateUserRequest, LoginRequest
from user_auth_service.core.refresh_tokens import RevokedSession
from user_auth_service.db.models import Account


class TestGetOutbox:
    """Tests for get_outbox dependency."""

    @pytest.mark.asyncio
    async def test_returns_outbox_writer(self) -> None:
        """Returns an OutboxWriter instance from async generator."""
        async_gen = get_outbox()
        result = await anext(async_gen)
        assert isinstance(result, OutboxWriter)


class TestRegister:
    """Tests for register endpoint."""

    @pytest.mark.asyncio
    async def test_registers_user_successfully(self) -> None:
        """Registers new user and returns response."""
        user_id = uuid.uuid4()
        session_family_id = uuid.uuid4()

        user_create = CreateUserRequest(
            email="new@example.com",
            password=SecretStr("SecurePassword123!"),
            display_name="\u00a0李\u2003小龍\u3000",
        )

        mock_db = create_mock_session()
        mock_db.commit = AsyncMock()
        mock_outbox = MagicMock()
        response = Response()
        mock_rate_limiter = MagicMock()

        mock_user = MagicMock(spec=Account)
        mock_user.id = user_id
        mock_user.email = "new@example.com"
        mock_user.display_name = "New User"

        with (
            patch(
                "user_auth_service.api.routers.auth.user_service.create_user",
                new_callable=AsyncMock,
                return_value=mock_user,
            ) as mock_create_user,
            patch(
                "user_auth_service.api.routers.auth.publish_user_created_event",
                new_callable=AsyncMock,
            ) as mock_publish,
            patch("user_auth_service.api.routers.auth.set_access_token_cookie"),
            patch("user_auth_service.api.routers.auth.set_refresh_token_cookie"),
            patch("user_auth_service.api.routers.auth.get_jwt_handler") as mock_get_jwt_handler,
            patch("user_auth_service.api.routers.auth.get_refresh_token_service") as mock_get_refresh,
        ):
            jwt_handler = MagicMock()
            jwt_handler.create_access_token.return_value = "access.jwt"
            mock_get_jwt_handler.return_value = jwt_handler

            refresh_service = MagicMock()
            refresh_service.create_session = AsyncMock(return_value=("refresh.token", session_family_id))
            mock_get_refresh.return_value = refresh_service

            result = await register(user_create, response, mock_db, mock_outbox, mock_rate_limiter)

        assert result.id == str(user_id)
        assert result.email == "new@example.com"
        mock_db.commit.assert_awaited_once()
        assert user_create.display_name == "李 小龍"
        mock_create_user.assert_awaited_once_with(mock_db, user_create)
        mock_publish.assert_awaited_once_with(mock_db, mock_outbox, mock_user)
        refresh_service.create_session.assert_awaited_once_with(mock_db, user_id)
        jwt_handler.create_access_token.assert_called_once_with(str(user_id), session_family_id=str(session_family_id))


class TestLogin:
    """Tests for login endpoint."""

    @pytest.mark.asyncio
    async def test_login_successful(self) -> None:
        """Successful login sets cookies and returns user metadata."""
        user_id = uuid.uuid4()
        session_family_id = uuid.uuid4()

        login_data = LoginRequest(
            email="user@example.com",
            password=SecretStr("password123"),
        )

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"X-Forwarded-For": "127.0.0.1"}
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        mock_db = create_mock_session()
        mock_db.commit = AsyncMock()
        response = Response()

        mock_user = MagicMock(spec=Account)
        mock_user.id = user_id
        mock_user.email = "user@example.com"
        mock_user.display_name = "User"

        with (
            patch(
                "user_auth_service.api.routers.auth.user_service.authenticate_user",
                new_callable=AsyncMock,
                return_value=mock_user,
            ),
            patch("user_auth_service.api.routers.auth.set_access_token_cookie"),
            patch("user_auth_service.api.routers.auth.set_refresh_token_cookie"),
            patch("user_auth_service.api.routers.auth.get_jwt_handler") as mock_get_jwt_handler,
            patch("user_auth_service.api.routers.auth.get_refresh_token_service") as mock_get_refresh,
            patch("user_auth_service.api.routers.auth.get_auth_rate_limiter") as mock_get_rate_limiter,
        ):
            jwt_handler = MagicMock()
            jwt_handler.create_access_token.return_value = "access.jwt"
            mock_get_jwt_handler.return_value = jwt_handler

            refresh_service = MagicMock()
            refresh_service.create_session = AsyncMock(return_value=("refresh.token", session_family_id))
            mock_get_refresh.return_value = refresh_service

            rate_limiter = MagicMock()
            rate_limiter.check_login = AsyncMock()
            rate_limiter.clear_failed_logins = AsyncMock()
            mock_get_rate_limiter.return_value = rate_limiter

            result = await login(mock_request, login_data, response, mock_db, rate_limiter)

        assert result.user_id == str(user_id)
        jwt_handler.create_access_token.assert_called_once_with(str(user_id), session_family_id=str(session_family_id))

    @pytest.mark.asyncio
    async def test_login_failed_records_and_raises(self) -> None:
        """Failed login records failed attempts and raises 401."""
        login_data = LoginRequest(
            email="user@example.com",
            password=SecretStr("wrong"),
        )

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"X-Forwarded-For": "10.0.0.1"}
        mock_request.client = MagicMock()
        mock_request.client.host = "10.0.0.1"

        mock_db = create_mock_session()
        response = Response()

        with (
            patch(
                "user_auth_service.api.routers.auth.user_service.authenticate_user",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("user_auth_service.api.routers.auth.get_auth_rate_limiter") as mock_get_rl,
        ):
            rate_limiter = MagicMock()
            rate_limiter.check_login = AsyncMock()
            rate_limiter.record_failed_login = AsyncMock()
            mock_get_rl.return_value = rate_limiter

            with pytest.raises(HTTPException) as exc_info:
                await login(mock_request, login_data, response, mock_db, rate_limiter)

            assert exc_info.value.status_code == 401
            assert rate_limiter.record_failed_login.await_count == 2


class TestExtractClientIp:
    """Tests for _extract_client_ip helper."""

    @pytest.mark.parametrize(
        ("peer", "forwarded", "trusted_proxies", "expected"),
        [
            ("192.0.2.10", "198.51.100.4", (), "192.0.2.10"),
            ("192.0.2.10", "198.51.100.4", ("10.0.0.0/8",), "192.0.2.10"),
            ("10.0.0.8", "198.51.100.4, 10.0.0.7", ("10.0.0.0/8",), "198.51.100.4"),
            ("2001:db8:1::8", "2001:db8:2::4", ("2001:db8:1::/64",), "2001:db8:2::4"),
            ("10.0.0.8", "not-an-ip", ("10.0.0.0/8",), "10.0.0.8"),
            ("10.0.0.8", "", ("10.0.0.0/8",), "10.0.0.8"),
        ],
    )
    def test_forwarding_is_used_only_from_trusted_peer(
        self,
        peer: str,
        forwarded: str,
        trusted_proxies: tuple[str, ...],
        expected: str,
    ) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"X-Forwarded-For": forwarded}
        request.client = MagicMock(host=peer)

        assert _extract_client_ip(request, trusted_proxies) == expected

    def test_no_forwarding_header_falls_back_to_peer(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = MagicMock(host="2001:db8::5")

        assert _extract_client_ip(request, ("2001:db8::/64",)) == "2001:db8::5"

    def test_returns_unknown_when_no_client(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"X-Forwarded-For": "198.51.100.4"}
        request.client = None

        assert _extract_client_ip(request, ("10.0.0.0/8",)) == "unknown"


class TestCheckRegisterRateLimit:
    """Tests for _check_register_rate_limit dependency."""

    @pytest.mark.asyncio
    async def test_returns_rate_limiter(self) -> None:
        """Checks rate limit and returns the rate limiter instance."""
        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.1")

        rate_limiter = MagicMock()
        rate_limiter.check_register = AsyncMock()

        with (
            patch("user_auth_service.api.routers.auth.get_auth_rate_limiter", return_value=rate_limiter),
            patch("user_auth_service.api.routers.auth.get_settings"),
        ):
            result = await _check_register_rate_limit(mock_request)

        assert result is rate_limiter
        rate_limiter.check_register.assert_awaited_once_with("192.168.1.1")


class TestCheckLoginRateLimit:
    """Tests for per-client login rate-limit attribution."""

    @pytest.mark.asyncio
    async def test_clients_behind_trusted_proxy_use_distinct_rate_limit_keys(self) -> None:
        rate_limiter = MagicMock()
        rate_limiter.check_login = AsyncMock()
        settings = MagicMock()
        settings.trusted_proxy_cidrs = ("10.0.0.0/8",)
        login_data = LoginRequest(email="person@example.com", password=SecretStr("valid-password"))

        with (
            patch("user_auth_service.api.routers.auth.get_auth_rate_limiter", return_value=rate_limiter),
            patch("user_auth_service.api.routers.auth.get_settings", return_value=settings),
        ):
            for forwarded in ("198.51.100.10", "198.51.100.11"):
                request = MagicMock(spec=Request)
                request.headers = {"X-Forwarded-For": forwarded}
                request.client = MagicMock(host="10.0.0.8")
                await _check_login_rate_limit(request, login_data)

        assert rate_limiter.check_login.await_args_list == [
            call("person@example.com"),
            call("198.51.100.10"),
            call("person@example.com"),
            call("198.51.100.11"),
        ]


class TestRefreshToken:
    """Tests for refresh_token endpoint."""

    @pytest.mark.asyncio
    async def test_refresh_success(self) -> None:
        """Successful refresh rotates token and sets new cookies."""
        user_id = uuid.uuid4()
        mock_request = MagicMock(spec=Request)
        mock_request.cookies = {"__Host-nohiki_rt": "old.refresh.token"}
        mock_db = create_mock_session()
        mock_db.commit = AsyncMock()
        active_account = MagicMock(spec=Account)
        active_account.is_active = True
        mock_db.get = AsyncMock(return_value=active_account)
        response = Response()

        with (
            patch(
                "user_auth_service.api.routers.auth.get_refresh_token_from_cookie",
                return_value="old.refresh.token",
            ),
            patch("user_auth_service.api.routers.auth.get_refresh_token_service") as mock_get_refresh,
            patch("user_auth_service.api.routers.auth.get_jwt_handler") as mock_get_jwt,
            patch("user_auth_service.api.routers.auth.set_access_token_cookie") as mock_set_at,
            patch("user_auth_service.api.routers.auth.set_refresh_token_cookie") as mock_set_rt,
            patch("user_auth_service.api.routers.auth.get_settings"),
        ):
            refresh_service = MagicMock()
            session_family_id = uuid.uuid4()
            refresh_service.rotate_token = AsyncMock(return_value=("new.refresh.token", user_id, session_family_id))
            mock_get_refresh.return_value = refresh_service

            jwt_handler = MagicMock()
            jwt_handler.create_access_token.return_value = "new.access.jwt"
            mock_get_jwt.return_value = jwt_handler

            result = await refresh_token(mock_request, response, mock_db, MagicMock())

        assert result["status"] == "refreshed"
        assert result["user_id"] == str(user_id)
        mock_set_at.assert_called_once()
        mock_set_rt.assert_called_once()
        mock_db.commit.assert_awaited_once()
        jwt_handler.create_access_token.assert_called_once_with(str(user_id), session_family_id=str(session_family_id))

    @pytest.mark.asyncio
    async def test_refresh_missing_token_raises(self) -> None:
        """Missing refresh token cookie raises 401."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies = {}
        mock_db = create_mock_session()
        response = Response()

        with (
            patch(
                "user_auth_service.api.routers.auth.get_refresh_token_from_cookie",
                return_value=None,
            ),
            patch("user_auth_service.api.routers.auth.get_settings"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await refresh_token(mock_request, response, mock_db, MagicMock())

            assert exc_info.value.status_code == 401
            assert "Refresh token required" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_refresh_reuse_publishes_family_revocation_before_commit_and_401(self) -> None:
        """Reuse publishes a durable family cutoff before rejecting the request."""
        mock_request = MagicMock(spec=Request)
        mock_request.cookies = {"__Host-nohiki_rt": "bad.token"}
        mock_db = create_mock_session()
        response = Response()
        outbox = MagicMock()
        account_id = uuid.uuid4()
        family_id = uuid.uuid4()
        jwt_handler = MagicMock()
        jwt_handler.config.access_token_expire_minutes = 15

        with (
            patch("user_auth_service.api.routers.auth.get_refresh_token_from_cookie", return_value="bad.token"),
            patch("user_auth_service.api.routers.auth.get_refresh_token_service") as mock_get_refresh,
            patch("user_auth_service.api.routers.auth.get_jwt_handler", return_value=jwt_handler),
            patch(
                "user_auth_service.api.routers.auth.publish_access_token_revoked_event",
                new_callable=AsyncMock,
            ) as publish,
            patch("user_auth_service.api.routers.auth.clear_auth_cookies") as mock_clear,
            patch("user_auth_service.api.routers.auth.get_settings"),
        ):
            refresh_service = MagicMock()
            refresh_service.rotate_token = AsyncMock(
                return_value=RevokedSession(account_id=account_id, session_family_id=family_id)
            )
            mock_get_refresh.return_value = refresh_service

            with pytest.raises(HTTPException) as exc_info:
                await refresh_token(mock_request, response, mock_db, outbox)

        assert exc_info.value.status_code == 401
        await_call = publish.await_args
        assert await_call is not None
        assert await_call.args[:2] == (mock_db, outbox)
        assert await_call.kwargs["user_id"] == account_id
        assert await_call.kwargs["jti"] is None
        assert await_call.kwargs["session_family_id"] == family_id
        mock_db.commit.assert_awaited_once()
        mock_clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_reuse_publish_failure_prevents_commit_and_cookie_clear(self) -> None:
        """A failed durable family event must leave the request failed closed."""
        request = MagicMock(spec=Request)
        request.cookies = {"__Host-nohiki_rt": "reused.token"}
        db = create_mock_session()
        response = Response()
        revoked = RevokedSession(account_id=uuid.uuid4(), session_family_id=uuid.uuid4())

        with (
            patch("user_auth_service.api.routers.auth.get_refresh_token_from_cookie", return_value="reused.token"),
            patch("user_auth_service.api.routers.auth.get_refresh_token_service") as get_refresh,
            patch("user_auth_service.api.routers.auth.get_jwt_handler") as get_jwt,
            patch(
                "user_auth_service.api.routers.auth.publish_access_token_revoked_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("outbox unavailable"),
            ),
            patch("user_auth_service.api.routers.auth.clear_auth_cookies") as clear,
            patch("user_auth_service.api.routers.auth.get_settings"),
        ):
            get_refresh.return_value.rotate_token = AsyncMock(return_value=revoked)
            get_jwt.return_value.config.access_token_expire_minutes = 15
            with pytest.raises(RuntimeError, match="outbox unavailable"):
                await refresh_token(request, response, db, MagicMock())

        db.commit.assert_not_awaited()
        clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_rejects_inactive_account_and_revokes_rotated_session(self) -> None:
        """A rotated token cannot revive an inactive account."""
        user_id = uuid.uuid4()
        mock_request = MagicMock(spec=Request)
        mock_request.cookies = {"__Host-nohiki_rt": "old.refresh.token"}
        mock_db = create_mock_session()
        inactive_account = MagicMock(spec=Account)
        inactive_account.is_active = False
        mock_db.get = AsyncMock(return_value=inactive_account)
        mock_db.commit = AsyncMock()
        response = Response()

        with (
            patch(
                "user_auth_service.api.routers.auth.get_refresh_token_from_cookie",
                return_value="old.refresh.token",
            ),
            patch("user_auth_service.api.routers.auth.get_refresh_token_service") as mock_get_refresh,
            patch("user_auth_service.api.routers.auth.clear_auth_cookies") as mock_clear,
            patch("user_auth_service.api.routers.auth.get_settings") as mock_get_settings,
        ):
            settings = MagicMock()
            mock_get_settings.return_value = settings
            refresh_service = MagicMock()
            refresh_service.rotate_token = AsyncMock(return_value=("new.refresh.token", user_id, uuid.uuid4()))
            refresh_service.revoke_session = AsyncMock(return_value=True)
            mock_get_refresh.return_value = refresh_service

            with pytest.raises(HTTPException) as exc_info:
                await refresh_token(mock_request, response, mock_db, MagicMock())

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Account is inactive"
        refresh_service.revoke_session.assert_awaited_once_with(mock_db, "new.refresh.token")
        mock_db.commit.assert_awaited_once()
        mock_clear.assert_called_once_with(response, settings)


class TestLogout:
    """Tests for transactional logout revocation ordering and branches."""

    @staticmethod
    def request(*, access: bool = False, refresh: bool = False) -> MagicMock:
        request = MagicMock(spec=Request)
        request.cookies = {
            **({"__Host-nohiki_at": "access.jwt"} if access else {}),
            **({"__Host-nohiki_rt": "refresh.token"} if refresh else {}),
        }
        return request

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("access", "refresh", "expects_publish", "expects_refresh", "expects_commit"),
        [
            (True, True, True, True, True),
            (True, False, True, False, True),
            (False, True, True, True, True),
            (False, False, False, False, False),
        ],
    )
    async def test_cookie_combinations(
        self,
        access: bool,  # noqa: FBT001
        refresh: bool,  # noqa: FBT001
        expects_publish: bool,  # noqa: FBT001
        expects_refresh: bool,  # noqa: FBT001
        expects_commit: bool,  # noqa: FBT001
    ) -> None:
        db = create_mock_session()
        db.commit = AsyncMock()
        outbox = MagicMock()
        response = Response()
        claims = (
            (
                uuid.uuid4(),
                uuid.uuid4(),
                datetime.now(UTC) + timedelta(minutes=5),
                uuid.uuid4(),
            )
            if access
            else None
        )

        with (
            patch(
                "user_auth_service.api.routers.auth.get_jwt_handler",
                return_value=MagicMock(config=MagicMock(access_token_expire_minutes=15)),
            ),
            patch("user_auth_service.api.routers.auth._extract_access_token_claims", return_value=claims),
            patch(
                "user_auth_service.api.routers.auth.get_refresh_token_from_cookie",
                return_value="refresh.token" if refresh else None,
            ),
            patch("user_auth_service.api.routers.auth.get_refresh_token_service") as get_refresh,
            patch(
                "user_auth_service.api.routers.auth.publish_access_token_revoked_event", new_callable=AsyncMock
            ) as publish,
            patch("user_auth_service.api.routers.auth._blacklist_access_token", new_callable=AsyncMock) as blacklist,
            patch("user_auth_service.api.routers.auth.clear_auth_cookies"),
        ):
            refresh_service = MagicMock()
            revoked_user_id = claims[0] if claims is not None else uuid.uuid4()
            revoked_family_id = claims[3] if claims is not None and claims[3] is not None else uuid.uuid4()
            refresh_service.revoke_session = AsyncMock(
                return_value=RevokedSession(
                    account_id=revoked_user_id,
                    session_family_id=revoked_family_id,
                )
                if refresh
                else None
            )
            refresh_service.revoke_session_family = AsyncMock(
                return_value=RevokedSession(
                    account_id=revoked_user_id,
                    session_family_id=revoked_family_id,
                )
                if access
                else None
            )
            get_refresh.return_value = refresh_service
            result = await logout(self.request(access=access, refresh=refresh), response, db, outbox)

        assert result == {"status": "logged_out"}
        assert publish.await_count == expects_publish
        assert refresh_service.revoke_session.await_count == expects_refresh
        assert refresh_service.revoke_session_family.await_count == access
        assert db.commit.await_count == expects_commit
        assert blacklist.await_count == access
        if refresh and not access:
            await_call = publish.await_args
            assert await_call is not None
            assert await_call.kwargs["user_id"] == revoked_user_id
            assert await_call.kwargs["jti"] is None
            assert await_call.kwargs["session_family_id"] == revoked_family_id

    @pytest.mark.asyncio
    async def test_access_cookie_only_revokes_claimed_family_transactionally(self) -> None:
        """An access cookie alone revokes its DB family before projection and cookie cleanup."""
        account_id = uuid.uuid4()
        family_id = uuid.uuid4()
        claims = (account_id, uuid.uuid4(), datetime.now(UTC) + timedelta(minutes=5), family_id)
        order: list[str] = []
        db = create_mock_session()

        async def revoke_family(_db: object, *, account_id: UUID, session_family_id: UUID) -> RevokedSession:
            order.append("family")
            return RevokedSession(account_id=account_id, session_family_id=session_family_id)

        async def publish_event(*_args: object, **_kwargs: object) -> None:
            order.append("publish")

        async def blacklist_token(*_args: object, **_kwargs: object) -> None:
            order.append("blacklist")

        def clear_cookies(*_args: object, **_kwargs: object) -> None:
            order.append("clear")

        db.commit = AsyncMock(side_effect=lambda: order.append("commit"))
        refresh_service = MagicMock()
        refresh_service.revoke_session_family = AsyncMock(side_effect=revoke_family)
        publish = AsyncMock(side_effect=publish_event)
        blacklist = AsyncMock(side_effect=blacklist_token)
        clear = MagicMock(side_effect=clear_cookies)

        with (
            patch(
                "user_auth_service.api.routers.auth.get_jwt_handler",
                return_value=MagicMock(config=MagicMock(access_token_expire_minutes=15)),
            ),
            patch("user_auth_service.api.routers.auth._extract_access_token_claims", return_value=claims),
            patch("user_auth_service.api.routers.auth.get_refresh_token_from_cookie", return_value=None),
            patch("user_auth_service.api.routers.auth.get_refresh_token_service", return_value=refresh_service),
            patch("user_auth_service.api.routers.auth.publish_access_token_revoked_event", publish),
            patch("user_auth_service.api.routers.auth._blacklist_access_token", blacklist),
            patch("user_auth_service.api.routers.auth.clear_auth_cookies", clear),
        ):
            result = await logout(self.request(access=True), Response(), db, MagicMock())

        assert result == {"status": "logged_out"}
        refresh_service.revoke_session_family.assert_awaited_once_with(
            db,
            account_id=account_id,
            session_family_id=family_id,
        )
        assert publish.await_count == 1
        assert db.commit.await_count == 1
        assert order[:3] == ["family", "publish", "commit"]
        assert order[-2:] == ["blacklist", "clear"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({"sub": "bad", "jti": str(uuid.uuid4()), "exp": 2**31}, id="malformed-sub"),
            pytest.param({"sub": str(uuid.uuid4()), "exp": 2**31}, id="missing-jti"),
            pytest.param(
                {
                    "sub": str(uuid.uuid4()),
                    "jti": str(uuid.uuid4()),
                    "exp": 2**31,
                    "session_family_id": "not-a-uuid",
                },
                id="malformed-family",
            ),
        ],
    )
    async def test_malformed_claims_do_not_write_revocation(self, payload: dict[str, object]) -> None:
        db = create_mock_session()
        with (
            patch("user_auth_service.api.routers.auth.get_access_token_from_cookie", return_value="token"),
            patch("user_auth_service.api.routers.auth.pyjwt.decode", return_value=payload),
            patch("user_auth_service.api.routers.auth.get_jwt_handler", return_value=MagicMock()),
            patch(
                "user_auth_service.api.routers.auth.publish_access_token_revoked_event", new_callable=AsyncMock
            ) as publish,
            patch("user_auth_service.api.routers.auth.clear_auth_cookies"),
        ):
            await logout(self.request(access=True), Response(), db, MagicMock())
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(__import__("jwt").ExpiredSignatureError(), id="expired"),
            pytest.param(__import__("jwt").InvalidTokenError(), id="invalid"),
        ],
    )
    async def test_invalid_tokens_do_not_write_revocation(self, error: Exception) -> None:
        db = create_mock_session()
        with (
            patch("user_auth_service.api.routers.auth.get_access_token_from_cookie", return_value="token"),
            patch("user_auth_service.api.routers.auth.pyjwt.decode", side_effect=error),
            patch("user_auth_service.api.routers.auth.get_jwt_handler", return_value=MagicMock()),
            patch(
                "user_auth_service.api.routers.auth.publish_access_token_revoked_event", new_callable=AsyncMock
            ) as publish,
            patch("user_auth_service.api.routers.auth.clear_auth_cookies"),
        ):
            await logout(self.request(access=True), Response(), db, MagicMock())
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_family_revocation_horizon_covers_configured_access_lifetime(self) -> None:
        db = create_mock_session()
        family_id = uuid.uuid4()
        token_expiry = datetime.now(UTC) + timedelta(seconds=5)
        claims = (uuid.uuid4(), uuid.uuid4(), token_expiry, family_id)
        jwt_handler = MagicMock()
        jwt_handler.config.access_token_expire_minutes = 15
        before = datetime.now(UTC)
        with (
            patch("user_auth_service.api.routers.auth._extract_access_token_claims", return_value=claims),
            patch("user_auth_service.api.routers.auth.get_jwt_handler", return_value=jwt_handler),
            patch(
                "user_auth_service.api.routers.auth.publish_access_token_revoked_event",
                new_callable=AsyncMock,
            ) as publish,
            patch("user_auth_service.api.routers.auth._blacklist_access_token", new_callable=AsyncMock),
            patch("user_auth_service.api.routers.auth.clear_auth_cookies"),
        ):
            await logout(self.request(access=True), Response(), db, MagicMock())

        await_call = publish.await_args
        assert await_call is not None
        assert await_call.kwargs["session_family_id"] == family_id
        assert await_call.kwargs["expires_at"] >= before + timedelta(minutes=15)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", ["outbox", "commit"])
    async def test_durable_failure_prevents_redis_and_cookie_clear(self, failure: str) -> None:
        db = create_mock_session()
        db.commit = AsyncMock(side_effect=RuntimeError("commit")) if failure == "commit" else AsyncMock()
        publish = AsyncMock(side_effect=RuntimeError("outbox")) if failure == "outbox" else AsyncMock()
        claims = (
            uuid.uuid4(),
            uuid.uuid4(),
            datetime.now(UTC) + timedelta(minutes=5),
            uuid.uuid4(),
        )
        with (  # noqa: SIM117
            patch(
                "user_auth_service.api.routers.auth.get_jwt_handler",
                return_value=MagicMock(config=MagicMock(access_token_expire_minutes=15)),
            ),
            patch("user_auth_service.api.routers.auth._extract_access_token_claims", return_value=claims),
            patch("user_auth_service.api.routers.auth.publish_access_token_revoked_event", publish),
            patch("user_auth_service.api.routers.auth._blacklist_access_token", new_callable=AsyncMock) as blacklist,
            patch("user_auth_service.api.routers.auth.clear_auth_cookies") as clear,
        ):
            with pytest.raises(RuntimeError):
                await logout(self.request(access=True), Response(), db, MagicMock())
        blacklist.assert_not_awaited()
        clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_failure_occurs_after_durable_commit(self) -> None:
        order: list[str] = []
        db = create_mock_session()
        db.commit = AsyncMock(side_effect=lambda: order.append("commit"))
        publish = AsyncMock(side_effect=lambda *_args, **_kwargs: order.append("outbox"))
        blacklist = AsyncMock(side_effect=RuntimeError("redis"))
        claims = (
            uuid.uuid4(),
            uuid.uuid4(),
            datetime.now(UTC) + timedelta(minutes=5),
            uuid.uuid4(),
        )
        with (  # noqa: SIM117
            patch(
                "user_auth_service.api.routers.auth.get_jwt_handler",
                return_value=MagicMock(config=MagicMock(access_token_expire_minutes=15)),
            ),
            patch("user_auth_service.api.routers.auth._extract_access_token_claims", return_value=claims),
            patch("user_auth_service.api.routers.auth.publish_access_token_revoked_event", publish),
            patch("user_auth_service.api.routers.auth._blacklist_access_token", blacklist),
            patch("user_auth_service.api.routers.auth.clear_auth_cookies") as clear,
        ):
            with pytest.raises(RuntimeError, match="redis"):
                await logout(self.request(access=True), Response(), db, MagicMock())
        assert order == ["outbox", "commit"]
        clear.assert_not_called()


class TestGetJwks:
    """Tests for JWKS endpoint."""

    @pytest.mark.asyncio
    async def test_returns_jwks(self) -> None:
        """Returns JWKS from JWT handler."""
        mock_jwks = {"keys": [{"kty": "RSA", "kid": "test-key"}]}

        with patch("user_auth_service.api.routers.auth.get_jwt_handler") as mock_get_jwt:
            jwt_handler = MagicMock()
            jwt_handler.get_jwks.return_value = mock_jwks
            mock_get_jwt.return_value = jwt_handler

            result = await get_jwks()

        assert result == mock_jwks

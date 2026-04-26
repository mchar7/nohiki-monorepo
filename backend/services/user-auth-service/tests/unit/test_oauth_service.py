"""Unit tests for user_auth_service.services.oauth_service module."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki_db_utils.testing import create_mock_session
from pydantic import SecretStr
from user_auth_service.core.config import (
    GitHubOAuthSettings,
    OAuthSettings,
)
from user_auth_service.core.oauth_clients import OAuthProvider
from user_auth_service.core.oauth_state import OAuthState, OAuthStateStorage
from user_auth_service.db.models import Account, OAuthIdentity
from user_auth_service.services.oauth_service import (
    ERROR_CANNOT_UNLINK,
    ERROR_INVALID_PROVIDER,
    ERROR_PROVIDER_DISABLED,
    ERROR_STATE_MISMATCH,
    OAuthError,
    OAuthResult,
    OAuthService,
    get_oauth_service,
    reset_oauth_service,
)


def _oauth_state(*, provider: str = "github", return_url: str = "/dashboard") -> OAuthState:
    return OAuthState(
        state="test-state",
        code_verifier="test-verifier",
        provider=provider,
        redirect_uri="http://localhost/callback",
        created_at=datetime.now(tz=UTC),
        return_url=return_url,
    )


class TestOAuthError:
    """Tests for OAuthError exception."""

    def test_error_initialization(self) -> None:
        """Verify OAuthError stores code and description."""
        error = OAuthError("test_code", "Test description")

        assert error.code == "test_code"
        assert error.description == "Test description"

    def test_error_message_format(self) -> None:
        """Verify OAuthError message includes code and description."""
        error = OAuthError("test_code", "Test description")

        assert str(error) == "test_code: Test description"


class TestOAuthResult:
    """Tests for OAuthResult dataclass."""

    def test_create_result(self) -> None:
        """Verify OAuthResult can be created."""
        account = MagicMock(spec=Account)
        result = OAuthResult(
            account=account,
            is_new_account=True,
            is_new_link=False,
        )

        assert result.account is account
        assert result.is_new_account is True
        assert result.is_new_link is False


class TestOAuthService:
    """Tests for OAuthService class."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings."""
        settings = MagicMock()
        settings.oauth = OAuthSettings(
            github=GitHubOAuthSettings(
                enabled=True,
                client_id="test-id",
                client_secret=SecretStr("test-secret"),
            )
        )
        return settings

    @pytest.fixture
    def mock_state_storage(self) -> AsyncMock:
        """Create mock state storage."""
        return AsyncMock(spec=OAuthStateStorage)

    @pytest.fixture
    def service(self, mock_settings: MagicMock, mock_state_storage: AsyncMock) -> OAuthService:
        """Create OAuthService instance."""
        return OAuthService(settings=mock_settings, state_storage=mock_state_storage)

    @pytest.fixture(autouse=True)
    def _reset_singleton(self) -> Generator[None]:
        """Reset singleton before each test."""
        reset_oauth_service()
        yield
        reset_oauth_service()

    def test_validate_provider_valid(self, service: OAuthService) -> None:
        """Verify _validate_provider accepts valid provider."""
        result = service._validate_provider("github")

        assert result == OAuthProvider.GITHUB

    def test_validate_provider_invalid(self, service: OAuthService) -> None:
        """Verify _validate_provider raises OAuthError for invalid provider."""
        with pytest.raises(OAuthError) as exc_info:
            service._validate_provider("unknown")

        assert exc_info.value.code == ERROR_INVALID_PROVIDER

    def test_validate_provider_unconfigured(self, service: OAuthService) -> None:
        """Verify _validate_provider raises OAuthError for unconfigured provider."""
        with pytest.raises(OAuthError) as exc_info:
            service._validate_provider("google")

        assert exc_info.value.code == ERROR_PROVIDER_DISABLED

    @pytest.mark.asyncio
    async def test_start_authorization_rejects_disabled_configured_provider(
        self, mock_state_storage: AsyncMock
    ) -> None:
        """Configured credentials do not enable an administratively disabled provider."""
        settings = MagicMock()
        settings.oauth = OAuthSettings(
            github=GitHubOAuthSettings(
                enabled=False,
                client_id="test-id",
                client_secret=SecretStr("test-secret"),
            )
        )
        service = OAuthService(settings=settings, state_storage=mock_state_storage)

        with pytest.raises(OAuthError) as exc_info:
            await service.start_authorization("github")

        assert exc_info.value.code == ERROR_PROVIDER_DISABLED
        mock_state_storage.store.assert_not_awaited()

    def test_build_callback_url(self, service: OAuthService) -> None:
        """Verify _build_callback_url constructs correct URL."""
        url = service._build_callback_url("github")

        assert url == "http://localhost:8000/api/v1/auth/oauth/github/callback"

    @pytest.mark.asyncio
    async def test_start_authorization(self, service: OAuthService, mock_state_storage: AsyncMock) -> None:
        """Verify start_authorization stores state and returns URL."""
        mock_state = OAuthState(
            state="test-state",
            code_verifier="test-verifier",
            provider="github",
            redirect_uri="http://localhost/callback",
            created_at=datetime.now(tz=UTC),
            return_url="/dashboard",
        )
        mock_state_storage.store.return_value = mock_state

        url, state = await service.start_authorization("github", "/jobs?tab=saved")

        assert isinstance(url, str)
        assert state == "test-state"
        mock_state_storage.store.assert_awaited_once_with(
            provider="github",
            redirect_uri="http://localhost:8000/api/v1/auth/oauth/github/callback",
            return_url="/jobs?tab=saved",
        )

    @pytest.mark.asyncio
    async def test_handle_callback_success(
        self,
        service: OAuthService,
        mock_state_storage: AsyncMock,
    ) -> None:
        """Verify handle_callback creates account on success."""
        mock_db = create_mock_session()
        mock_state = OAuthState(
            state="test-state",
            code_verifier="test-verifier",
            provider="github",
            redirect_uri="http://localhost/callback",
            created_at=datetime.now(tz=UTC),
            return_url="/dashboard",
        )
        mock_state_storage.retrieve_and_delete.return_value = mock_state

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result
        mock_db.get.return_value = None

        with patch("user_auth_service.services.oauth_service.create_oauth_client") as mock_create_client:
            mock_client = AsyncMock()
            mock_client.exchange_code.return_value = {"access_token": "test-token"}
            mock_client.fetch_user_profile.return_value = MagicMock(
                provider=OAuthProvider.GITHUB,
                provider_user_id="12345",
                email="user@example.com",
                username="testuser",
                display_name="Test User",
                raw_profile={},
            )
            mock_create_client.return_value = mock_client

            result = await service.handle_callback(db=mock_db, provider="github", code="test-code", state=mock_state)

            assert isinstance(result, OAuthResult)
            assert result.is_new_account is True

    @pytest.mark.asyncio
    async def test_handle_callback_state_provider_mismatch(
        self, service: OAuthService, mock_state_storage: AsyncMock
    ) -> None:
        """Verify handle_callback raises error for provider mismatch."""
        mock_db = create_mock_session()
        mock_state = OAuthState(
            state="test-state",
            code_verifier="test-verifier",
            provider="google",
            redirect_uri="http://localhost/callback",
            created_at=datetime.now(tz=UTC),
            return_url="/dashboard",
        )
        mock_state_storage.retrieve_and_delete.return_value = mock_state

        with pytest.raises(OAuthError) as exc_info:
            await service.handle_callback(db=mock_db, provider="github", code="test-code", state=mock_state)

        assert exc_info.value.code == ERROR_STATE_MISMATCH

    @pytest.mark.asyncio
    async def test_cookie_mismatch_does_not_consume_state(
        self, service: OAuthService, mock_state_storage: AsyncMock
    ) -> None:
        with pytest.raises(OAuthError) as exc_info:
            await service.consume_callback_state("github", "query-state", "other-browser-state")

        assert exc_info.value.code == ERROR_STATE_MISMATCH
        mock_state_storage.retrieve_and_delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_matching_binding_consumes_state_once(
        self, service: OAuthService, mock_state_storage: AsyncMock
    ) -> None:
        stored = _oauth_state()
        mock_state_storage.retrieve_and_delete.side_effect = [stored, None]

        assert await service.consume_callback_state("github", "test-state", "test-state") is stored
        with pytest.raises(OAuthError) as exc_info:
            await service.consume_callback_state("github", "test-state", "test-state")

        assert exc_info.value.code == ERROR_STATE_MISMATCH
        assert mock_state_storage.retrieve_and_delete.await_count == 2

    @pytest.mark.asyncio
    async def test_get_linked_identities(self, service: OAuthService) -> None:
        """Verify get_linked_identities returns list of identities."""
        mock_db = create_mock_session()
        account_id = uuid4()

        mock_identity1 = MagicMock(spec=OAuthIdentity)
        mock_identity2 = MagicMock(spec=OAuthIdentity)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_identity1, mock_identity2]

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        identities = await service.get_linked_identities(db=mock_db, account_id=account_id)

        assert len(identities) == 2
        assert mock_identity1 in identities
        assert mock_identity2 in identities

    @pytest.mark.asyncio
    async def test_unlink_identity_success(self, service: OAuthService) -> None:
        """Verify unlink_identity removes identity."""
        mock_db = create_mock_session()
        account_id = uuid4()

        mock_account = MagicMock(spec=Account)
        mock_account.has_password = True
        mock_db.get.return_value = mock_account

        mock_identity = MagicMock(spec=OAuthIdentity)
        mock_identity.provider = "github"

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_identity]

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        result = await service.unlink_identity(db=mock_db, account_id=account_id, provider="github")

        assert result is True
        mock_db.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_unlink_identity_cannot_unlink_last_method(self, service: OAuthService) -> None:
        """Verify unlink_identity raises error when removing last auth method."""
        mock_db = create_mock_session()
        account_id = uuid4()

        mock_account = MagicMock(spec=Account)
        mock_account.has_password = False
        mock_db.get.return_value = mock_account

        mock_identity = MagicMock(spec=OAuthIdentity)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_identity]

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        with pytest.raises(OAuthError) as exc_info:
            await service.unlink_identity(db=mock_db, account_id=account_id, provider="github")

        assert exc_info.value.code == ERROR_CANNOT_UNLINK


class TestHandleCallbackEdgeCases:
    """Tests for handle_callback edge cases and error paths."""

    @pytest.fixture
    def mock_state_storage(self) -> AsyncMock:
        """Create mock state storage."""
        return AsyncMock(spec=OAuthStateStorage)

    @pytest.fixture
    def service(self, mock_state_storage: AsyncMock) -> OAuthService:
        """Create OAuthService with mocked dependencies."""
        mock_settings = MagicMock()
        mock_settings.oauth = OAuthSettings(
            github=GitHubOAuthSettings(
                enabled=True,
                client_id="test-id",
                client_secret=SecretStr("test-secret"),
            ),
        )
        return OAuthService(settings=mock_settings, state_storage=mock_state_storage)

    def _valid_state(self) -> OAuthState:
        return OAuthState(
            state="test-state",
            code_verifier="test-verifier",
            provider="github",
            redirect_uri="http://localhost/callback",
            created_at=datetime.now(tz=UTC),
            return_url="/dashboard",
        )

    @pytest.mark.asyncio
    async def test_no_access_token_raises(self, service: OAuthService, mock_state_storage: AsyncMock) -> None:
        """Raises OAuthError when token response has no access_token."""
        mock_db = create_mock_session()
        mock_state_storage.retrieve_and_delete.return_value = self._valid_state()

        with patch("user_auth_service.services.oauth_service.create_oauth_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.exchange_code.return_value = {"token_type": "bearer"}
            mock_create.return_value = mock_client

            with pytest.raises(OAuthError) as exc_info:
                await service.handle_callback(db=mock_db, provider="github", code="code", state=_oauth_state())

            assert exc_info.value.code == "token_exchange_failed"

    @pytest.mark.asyncio
    async def test_exchange_code_reraises_oauth_error(
        self, service: OAuthService, mock_state_storage: AsyncMock
    ) -> None:
        """Re-raises OAuthError from exchange_code without wrapping."""
        mock_db = create_mock_session()
        mock_state_storage.retrieve_and_delete.return_value = self._valid_state()

        with patch("user_auth_service.services.oauth_service.create_oauth_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.exchange_code.side_effect = OAuthError("custom_code", "custom msg")
            mock_create.return_value = mock_client

            with pytest.raises(OAuthError) as exc_info:
                await service.handle_callback(db=mock_db, provider="github", code="code", state=_oauth_state())

            assert exc_info.value.code == "custom_code"

    @pytest.mark.asyncio
    async def test_exchange_code_wraps_unexpected_error(
        self, service: OAuthService, mock_state_storage: AsyncMock
    ) -> None:
        """Wraps unexpected errors from exchange_code in OAuthError."""
        mock_db = create_mock_session()
        mock_state_storage.retrieve_and_delete.return_value = self._valid_state()

        with patch("user_auth_service.services.oauth_service.create_oauth_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.exchange_code.side_effect = RuntimeError("network error")
            mock_create.return_value = mock_client

            with pytest.raises(OAuthError) as exc_info:
                await service.handle_callback(db=mock_db, provider="github", code="code", state=_oauth_state())

            assert exc_info.value.code == "token_exchange_failed"

    @pytest.mark.asyncio
    async def test_fetch_profile_reraises_oauth_error(
        self, service: OAuthService, mock_state_storage: AsyncMock
    ) -> None:
        """Re-raises OAuthError from fetch_user_profile without wrapping."""
        mock_db = create_mock_session()
        mock_state_storage.retrieve_and_delete.return_value = self._valid_state()

        with patch("user_auth_service.services.oauth_service.create_oauth_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.exchange_code.return_value = {"access_token": "tok"}
            mock_client.fetch_user_profile.side_effect = OAuthError("profile_custom", "custom")
            mock_create.return_value = mock_client

            with pytest.raises(OAuthError) as exc_info:
                await service.handle_callback(db=mock_db, provider="github", code="code", state=_oauth_state())

            assert exc_info.value.code == "profile_custom"

    @pytest.mark.asyncio
    async def test_fetch_profile_wraps_unexpected_error(
        self, service: OAuthService, mock_state_storage: AsyncMock
    ) -> None:
        """Wraps unexpected errors from fetch_user_profile in OAuthError."""
        mock_db = create_mock_session()
        mock_state_storage.retrieve_and_delete.return_value = self._valid_state()

        with patch("user_auth_service.services.oauth_service.create_oauth_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.exchange_code.return_value = {"access_token": "tok"}
            mock_client.fetch_user_profile.side_effect = RuntimeError("API down")
            mock_create.return_value = mock_client

            with pytest.raises(OAuthError) as exc_info:
                await service.handle_callback(db=mock_db, provider="github", code="code", state=_oauth_state())

            assert exc_info.value.code == "profile_fetch_failed"

    @pytest.mark.asyncio
    async def test_existing_identity_returns_existing_account(
        self, service: OAuthService, mock_state_storage: AsyncMock
    ) -> None:
        """Returns existing account when identity already linked."""
        mock_db = create_mock_session()
        mock_state_storage.retrieve_and_delete.return_value = self._valid_state()

        mock_account = MagicMock(spec=Account)
        mock_account.id = uuid4()

        mock_identity = MagicMock(spec=OAuthIdentity)
        mock_identity.account = mock_account

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_identity
        mock_db.execute.return_value = mock_result

        with patch("user_auth_service.services.oauth_service.create_oauth_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.exchange_code.return_value = {"access_token": "tok"}
            mock_client.fetch_user_profile.return_value = MagicMock(
                provider=OAuthProvider.GITHUB,
                provider_user_id="12345",
                email="user@example.com",
                username="testuser",
                display_name="Test User",
                raw_profile={},
            )
            mock_create.return_value = mock_client

            result = await service.handle_callback(db=mock_db, provider="github", code="code", state=_oauth_state())

        assert result.is_new_account is False
        assert result.is_new_link is False
        assert result.account is mock_account

    @pytest.mark.asyncio
    async def test_links_to_existing_account_by_email(
        self, service: OAuthService, mock_state_storage: AsyncMock
    ) -> None:
        """Links new identity to existing account found by email."""
        mock_db = create_mock_session()
        mock_state_storage.retrieve_and_delete.return_value = self._valid_state()

        mock_account = MagicMock(spec=Account)
        mock_account.id = uuid4()

        mock_result_no_identity = MagicMock()
        mock_result_no_identity.scalar_one_or_none.return_value = None

        mock_result_account = MagicMock()
        mock_result_account.scalar_one_or_none.return_value = mock_account

        mock_db.execute.side_effect = [mock_result_no_identity, mock_result_account]

        with patch("user_auth_service.services.oauth_service.create_oauth_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.exchange_code.return_value = {"access_token": "tok"}
            mock_client.fetch_user_profile.return_value = MagicMock(
                provider=OAuthProvider.GITHUB,
                provider_user_id="12345",
                email="existing@example.com",
                username="testuser",
                display_name="Test User",
                raw_profile={},
            )
            mock_create.return_value = mock_client

            result = await service.handle_callback(db=mock_db, provider="github", code="code", state=_oauth_state())

        assert result.is_new_account is False
        assert result.is_new_link is True

    @pytest.mark.asyncio
    async def test_unlink_account_not_found(self, service: OAuthService) -> None:
        """Returns False when account not found for unlink."""
        mock_db = create_mock_session()
        mock_db.get.return_value = None

        result = await service.unlink_identity(db=mock_db, account_id=uuid4(), provider="github")
        assert result is False

    @pytest.mark.asyncio
    async def test_unlink_identity_not_found(self, service: OAuthService) -> None:
        """Returns False when identity not found for provider."""
        mock_db = create_mock_session()
        mock_account = MagicMock(spec=Account)
        mock_account.has_password = True
        mock_db.get.return_value = mock_account

        mock_identity = MagicMock(spec=OAuthIdentity)
        mock_identity.provider = "google"

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_identity]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        result = await service.unlink_identity(db=mock_db, account_id=uuid4(), provider="github")
        assert result is False


class TestFindIdentityInList:
    """Tests for _find_identity_in_list static method."""

    def test_returns_none_when_not_found(self) -> None:
        """Returns None when provider not in list."""
        identity = MagicMock(spec=OAuthIdentity)
        identity.provider = "google"

        result = OAuthService._find_identity_in_list([identity], "github")
        assert result is None

    def test_returns_matching_identity(self) -> None:
        """Returns identity matching provider."""
        identity = MagicMock(spec=OAuthIdentity)
        identity.provider = "github"

        result = OAuthService._find_identity_in_list([identity], "github")
        assert result is identity


class TestOAuthServiceSingleton:
    """Tests for OAuthService singleton management."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self) -> Generator[None]:
        """Reset singleton before each test."""
        reset_oauth_service()
        yield
        reset_oauth_service()

    def test_get_instance_creates_singleton(self) -> None:
        """Verify get_instance creates singleton."""
        mock_settings = MagicMock()
        mock_settings.oauth = OAuthSettings()
        mock_state_storage = AsyncMock(spec=OAuthStateStorage)

        service1 = OAuthService.get_instance(settings=mock_settings, state_storage=mock_state_storage)
        service2 = OAuthService.get_instance(settings=mock_settings, state_storage=mock_state_storage)

        assert service1 is service2

    def test_reset_instance_clears_singleton(self) -> None:
        """Verify reset_instance clears singleton."""
        mock_settings = MagicMock()
        mock_settings.oauth = OAuthSettings()
        mock_state_storage = AsyncMock(spec=OAuthStateStorage)

        service1 = OAuthService.get_instance(settings=mock_settings, state_storage=mock_state_storage)
        OAuthService.reset_instance()
        service2 = OAuthService.get_instance(settings=mock_settings, state_storage=mock_state_storage)

        assert service1 is not service2

    def test_get_oauth_service_uses_singleton(self) -> None:
        """Verify get_oauth_service uses singleton."""
        mock_settings = MagicMock()
        mock_settings.oauth = OAuthSettings()
        mock_state_storage = AsyncMock(spec=OAuthStateStorage)

        service1 = get_oauth_service(settings=mock_settings, state_storage=mock_state_storage)
        service2 = get_oauth_service(settings=mock_settings, state_storage=mock_state_storage)

        assert service1 is service2

    def test_reset_oauth_service_clears_singleton(self) -> None:
        """Verify reset_oauth_service clears singleton via function."""
        mock_settings = MagicMock()
        mock_settings.oauth = OAuthSettings()
        mock_state_storage = AsyncMock(spec=OAuthStateStorage)

        service1 = get_oauth_service(settings=mock_settings, state_storage=mock_state_storage)
        reset_oauth_service()
        service2 = get_oauth_service(settings=mock_settings, state_storage=mock_state_storage)

        assert service1 is not service2

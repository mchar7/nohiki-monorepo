"""OAuth authentication service with account linking logic."""

from __future__ import annotations

from dataclasses import dataclass
from secrets import compare_digest
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from user_auth_service.core.oauth_clients import (
    OAuthClient,
    OAuthProvider,
    OAuthUserProfile,
    create_oauth_client,
    is_valid_provider,
)
from user_auth_service.core.oauth_state import OAuthState, OAuthStateStorage
from user_auth_service.db.models import Account, OAuthIdentity

if TYPE_CHECKING:
    from user_auth_service.core.config import Settings


ERROR_INVALID_PROVIDER = "invalid_provider"
ERROR_PROVIDER_DISABLED = "provider_disabled"
ERROR_STATE_MISMATCH = "state_mismatch"
ERROR_CODE_EXCHANGE_FAILED = "token_exchange_failed"
ERROR_PROFILE_FETCH_FAILED = "profile_fetch_failed"
ERROR_CANNOT_UNLINK = "cannot_unlink"


class OAuthError(Exception):
    """OAuth authentication error."""

    def __init__(self, code: str, description: str) -> None:
        """Initialize OAuth error.

        Args:
            code: Error code identifier.
            description: Human-readable error description.

        """
        self.code = code
        self.description = description
        super().__init__(f"{code}: {description}")


@dataclass(frozen=True, slots=True)
class OAuthResult:
    """Result of OAuth authentication."""

    account: Account
    is_new_account: bool
    is_new_link: bool


class OAuthService:
    """OAuth authentication and account linking service."""

    _instance: OAuthService | None = None

    def __init__(
        self,
        settings: Settings,
        state_storage: OAuthStateStorage,
    ) -> None:
        """Initialize OAuth service.

        Args:
            settings: Application settings.
            state_storage: OAuth state storage instance.

        """
        self._settings = settings
        self._state_storage = state_storage
        self._oauth_settings = settings.oauth

    @classmethod
    def get_instance(
        cls,
        settings: Settings,
        state_storage: OAuthStateStorage,
    ) -> OAuthService:
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls(settings=settings, state_storage=state_storage)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None

    def _validate_provider(self, provider: str) -> OAuthProvider:
        """Validate and convert provider string to enum."""
        if not is_valid_provider(provider):
            msg = f"Unknown provider: {provider}"
            raise OAuthError(ERROR_INVALID_PROVIDER, msg)

        oauth_provider = OAuthProvider(provider)
        provider_settings = self._oauth_settings.get_provider(provider)

        if provider_settings is None or not provider_settings.enabled or not provider_settings.is_configured():
            msg = f"Provider disabled or not configured: {provider}"
            raise OAuthError(ERROR_PROVIDER_DISABLED, msg)

        return oauth_provider

    def _build_callback_url(self, provider: str) -> str:
        """Build OAuth callback URL for provider."""
        return f"{self._oauth_settings.callback_base_url}/api/v1/auth/oauth/{provider}/callback"

    async def start_authorization(
        self,
        provider: str,
        return_url: str | None = None,
    ) -> tuple[str, str]:
        """Start OAuth authorization and return its URL and browser-binding state."""
        oauth_provider = self._validate_provider(provider)
        callback_url = self._build_callback_url(provider)
        state = await self._state_storage.store(
            provider=provider,
            redirect_uri=callback_url,
            return_url=return_url or "/",
        )
        client = create_oauth_client(oauth_provider, self._oauth_settings)
        authorization_url = client.get_authorization_url(
            redirect_uri=callback_url,
            state=state.state,
            code_verifier=state.code_verifier,
        )
        return authorization_url, state.state

    async def consume_callback_state(
        self,
        provider: str,
        query_state: str,
        cookie_state: str | None,
    ) -> OAuthState:
        """Verify the browser binding, then consume and validate one-time state."""
        if cookie_state is None or not compare_digest(query_state, cookie_state):
            msg = "OAuth state does not match the initiating browser"
            raise OAuthError(ERROR_STATE_MISMATCH, msg)

        stored_state = await self._state_storage.retrieve_and_delete(query_state)
        if stored_state is None:
            msg = "Invalid or expired state parameter"
            raise OAuthError(ERROR_STATE_MISMATCH, msg)
        if stored_state.provider != provider:
            msg = "Provider mismatch in state"
            raise OAuthError(ERROR_STATE_MISMATCH, msg)
        return stored_state

    async def handle_callback(
        self,
        db: AsyncSession,
        provider: str,
        code: str,
        state: OAuthState,
    ) -> OAuthResult:
        """Exchange a callback code using already-consumed OAuth state."""
        if state.provider != provider:
            msg = "Provider mismatch in state"
            raise OAuthError(ERROR_STATE_MISMATCH, msg)

        oauth_provider = OAuthProvider(provider)
        client = create_oauth_client(oauth_provider, self._oauth_settings)

        token_data = await self._exchange_code_safely(client, code, state.redirect_uri, state.code_verifier)

        access_token = token_data.get("access_token")
        if not access_token or not isinstance(access_token, str):
            msg = "No access token in response"
            raise OAuthError(ERROR_CODE_EXCHANGE_FAILED, msg)

        profile = await self._fetch_profile_safely(client, access_token)
        return await self._resolve_account(db, profile)

    async def _exchange_code_safely(
        self,
        client: OAuthClient,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, object]:
        """Exchange authorization code for tokens with error handling."""
        try:
            return await client.exchange_code(
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
        except OAuthError:
            raise
        except Exception as e:
            msg = str(e)
            raise OAuthError(ERROR_CODE_EXCHANGE_FAILED, msg) from e

    async def _fetch_profile_safely(
        self,
        client: OAuthClient,
        access_token: str,
    ) -> OAuthUserProfile:
        """Fetch user profile with error handling."""
        try:
            return await client.fetch_user_profile(access_token)
        except OAuthError:
            raise
        except Exception as e:
            msg = str(e)
            raise OAuthError(ERROR_PROFILE_FETCH_FAILED, msg) from e

    async def _resolve_account(
        self,
        db: AsyncSession,
        profile: OAuthUserProfile,
    ) -> OAuthResult:
        """Resolve OAuth profile to account (find existing or create new)."""
        existing_identity = await self._find_identity(db, profile.provider, profile.provider_user_id)

        if existing_identity is not None:
            return OAuthResult(
                account=existing_identity.account,
                is_new_account=False,
                is_new_link=False,
            )

        if profile.email:
            existing_account = await self._find_account_by_email(db, profile.email)
            if existing_account is not None:
                await self._create_identity(db, existing_account.id, profile)
                return OAuthResult(
                    account=existing_account,
                    is_new_account=False,
                    is_new_link=True,
                )

        new_account = await self._create_account(db, profile)
        await self._create_identity(db, new_account.id, profile)

        return OAuthResult(
            account=new_account,
            is_new_account=True,
            is_new_link=True,
        )

    async def _find_identity(
        self,
        db: AsyncSession,
        provider: OAuthProvider,
        provider_user_id: str,
    ) -> OAuthIdentity | None:
        """Find existing OAuth identity."""
        stmt = (
            select(OAuthIdentity)
            .options(joinedload(OAuthIdentity.account))
            .where(OAuthIdentity.provider == provider.value)
            .where(OAuthIdentity.provider_user_id == provider_user_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_account_by_email(
        self,
        db: AsyncSession,
        email: str,
    ) -> Account | None:
        """Find existing account by email."""
        stmt = select(Account).where(Account.email == email)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _create_account(
        self,
        db: AsyncSession,
        profile: OAuthUserProfile,
    ) -> Account:
        """Create new account from OAuth profile."""
        email = profile.email or f"{profile.provider_user_id}@{profile.provider}.oauth"
        account = Account(
            email=email,
            hashed_password=None,
            display_name=profile.display_name,
            is_active=True,
            is_verified=profile.email is not None,
        )
        db.add(account)
        await db.flush()
        return account

    async def _create_identity(
        self,
        db: AsyncSession,
        account_id: UUID,
        profile: OAuthUserProfile,
    ) -> OAuthIdentity:
        """Create OAuth identity linked to account."""
        identity = OAuthIdentity(
            account_id=account_id,
            provider=profile.provider.value,
            provider_user_id=profile.provider_user_id,
            provider_email=profile.email,
            provider_username=profile.username,
            raw_profile=profile.raw_profile,
        )
        db.add(identity)
        await db.flush()
        return identity

    async def get_linked_identities(
        self,
        db: AsyncSession,
        account_id: UUID,
    ) -> list[OAuthIdentity]:
        """Get all OAuth identities linked to account."""
        stmt = select(OAuthIdentity).where(OAuthIdentity.account_id == account_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def unlink_identity(
        self,
        db: AsyncSession,
        account_id: UUID,
        provider: str,
    ) -> bool:
        """Unlink OAuth identity from account.

        Returns True if unlinked, False if not found.
        Raises OAuthError if this would leave account with no auth method.
        """
        account = await db.get(Account, account_id)
        if account is None:
            return False

        identities = await self.get_linked_identities(db, account_id)
        identity_count = len(identities)

        if identity_count <= 1 and not account.has_password:
            msg = "Cannot unlink only authentication method"
            raise OAuthError(ERROR_CANNOT_UNLINK, msg)

        identity = self._find_identity_in_list(identities, provider)
        if identity is None:
            return False

        await db.delete(identity)
        await db.flush()
        return True

    @staticmethod
    def _find_identity_in_list(
        identities: list[OAuthIdentity],
        provider: str,
    ) -> OAuthIdentity | None:
        """Find identity by provider in list."""
        for identity in identities:
            if identity.provider == provider:
                return identity
        return None


def get_oauth_service(
    settings: Settings,
    state_storage: OAuthStateStorage,
) -> OAuthService:
    """Get or create OAuth service singleton."""
    return OAuthService.get_instance(settings=settings, state_storage=state_storage)


def reset_oauth_service() -> None:
    """Reset OAuth service singleton (for testing)."""
    OAuthService.reset_instance()

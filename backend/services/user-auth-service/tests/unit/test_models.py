"""Unit tests for database models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import String
from user_auth_service.db.models import Account, OAuthIdentity, RefreshToken


class TestAccountModel:
    """Tests for Account model."""

    def test_account_creation(self) -> None:
        """Test creating an Account instance."""
        account = Account(
            email="test@example.com",
            hashed_password="hashed_password_123",
            display_name="Test User",
            first_name="Test",
            last_name="User",
        )

        assert account.email == "test@example.com"
        assert account.hashed_password == "hashed_password_123"
        assert account.display_name == "Test User"
        assert account.first_name == "Test"
        assert account.last_name == "User"
        # Note: is_active and is_verified defaults are set by DB, not in Python

    def test_account_name_column_lengths_match_proto(self) -> None:
        """Account names accept every proto-valid value."""
        first_name_type = Account.__table__.c.first_name.type
        last_name_type = Account.__table__.c.last_name.type
        assert isinstance(first_name_type, String)
        assert isinstance(last_name_type, String)
        assert first_name_type.length == 100
        assert last_name_type.length == 100

    def test_account_repr(self) -> None:
        """Test Account __repr__ method."""
        account = Account(
            id=uuid.uuid4(),
            email="test@example.com",
            hashed_password="hashed_password_123",
        )

        repr_str = repr(account)

        assert "Account" in repr_str
        assert str(account.id) in repr_str
        assert "test@example.com" in repr_str

    def test_account_with_optional_fields_none(self) -> None:
        """Test Account with optional fields set to None."""
        account = Account(
            email="minimal@example.com",
            hashed_password="hashed_password_123",
            display_name=None,
            first_name=None,
            last_name=None,
        )

        assert account.email == "minimal@example.com"
        assert account.display_name is None
        assert account.first_name is None
        assert account.last_name is None

    def test_account_has_password_with_password(self) -> None:
        """Test has_password property returns True when password is set."""
        account = Account(
            email="test@example.com",
            hashed_password="hashed_password_123",
        )

        assert account.has_password is True

    def test_account_has_password_without_password(self) -> None:
        """Test has_password property returns False for OAuth-only accounts."""
        account = Account(
            email="oauth@example.com",
            hashed_password=None,
        )

        assert account.has_password is False

    def test_account_without_password_oauth_only(self) -> None:
        """Test Account can be created without password (OAuth-only flow)."""
        account = Account(
            email="oauth-only@example.com",
            hashed_password=None,
            display_name="OAuth User",
        )

        assert account.email == "oauth-only@example.com"
        assert account.hashed_password is None
        assert account.has_password is False


class TestRefreshTokenModel:
    """Tests for RefreshToken model."""

    def test_refresh_token_creation(self) -> None:
        """Test creating a RefreshToken instance."""
        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + timedelta(days=30)

        token = RefreshToken(
            account_id=account_id,
            token_hash="argon2id$hashed_token",
            session_family_id=session_family_id,
            expires_at=expires_at,
        )

        assert token.account_id == account_id
        assert token.token_hash == "argon2id$hashed_token"
        assert token.session_family_id == session_family_id
        assert token.expires_at == expires_at
        assert token.used_at is None
        # Note: is_revoked default is set by DB, not in Python

    def test_refresh_token_repr(self) -> None:
        """Test RefreshToken __repr__ method."""
        token_id = uuid.uuid4()
        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + timedelta(days=30)

        token = RefreshToken(
            id=token_id,
            account_id=account_id,
            token_hash="argon2id$hashed_token",
            session_family_id=session_family_id,
            expires_at=expires_at,
        )

        repr_str = repr(token)

        assert "RefreshToken" in repr_str
        assert str(token_id) in repr_str
        assert str(account_id) in repr_str
        assert str(session_family_id) in repr_str

    def test_refresh_token_with_used_at(self) -> None:
        """Test RefreshToken with used_at timestamp."""
        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + timedelta(days=30)
        used_at = datetime.now(UTC)

        token = RefreshToken(
            account_id=account_id,
            token_hash="argon2id$hashed_token",
            session_family_id=session_family_id,
            expires_at=expires_at,
            used_at=used_at,
        )

        assert token.used_at == used_at

    def test_refresh_token_revoked(self) -> None:
        """Test RefreshToken when revoked."""
        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + timedelta(days=30)

        token = RefreshToken(
            account_id=account_id,
            token_hash="argon2id$hashed_token",
            session_family_id=session_family_id,
            expires_at=expires_at,
            is_revoked=True,
        )

        assert token.is_revoked is True


class TestOAuthIdentityModel:
    """Tests for OAuthIdentity model."""

    def test_oauth_identity_creation_minimal(self) -> None:
        """Test creating an OAuthIdentity with required fields only."""
        account_id = uuid.uuid4()

        identity = OAuthIdentity(
            account_id=account_id,
            provider="google",
            provider_user_id="123456789",
        )

        assert identity.account_id == account_id
        assert identity.provider == "google"
        assert identity.provider_user_id == "123456789"
        assert identity.provider_email is None
        assert identity.provider_username is None
        assert identity.access_token_encrypted is None
        assert identity.refresh_token_encrypted is None
        assert identity.token_expires_at is None
        assert identity.raw_profile is None

    def test_oauth_identity_creation_full(self) -> None:
        """Test creating an OAuthIdentity with all fields."""
        account_id = uuid.uuid4()
        token_expires = datetime.now(UTC) + timedelta(hours=1)
        raw_profile = {"name": "Test User", "picture": "https://example.com/photo.jpg"}

        identity = OAuthIdentity(
            account_id=account_id,
            provider="github",
            provider_user_id="gh_987654321",
            provider_email="test@github.com",
            provider_username="testuser",
            access_token_encrypted="encrypted_access_token",
            refresh_token_encrypted="encrypted_refresh_token",
            token_expires_at=token_expires,
            raw_profile=raw_profile,
        )

        assert identity.account_id == account_id
        assert identity.provider == "github"
        assert identity.provider_user_id == "gh_987654321"
        assert identity.provider_email == "test@github.com"
        assert identity.provider_username == "testuser"
        assert identity.access_token_encrypted == "encrypted_access_token"
        assert identity.refresh_token_encrypted == "encrypted_refresh_token"
        assert identity.token_expires_at == token_expires
        assert identity.raw_profile == raw_profile

    def test_oauth_identity_repr(self) -> None:
        """Test OAuthIdentity __repr__ method."""
        identity_id = uuid.uuid4()
        account_id = uuid.uuid4()

        identity = OAuthIdentity(
            id=identity_id,
            account_id=account_id,
            provider="google",
            provider_user_id="123456789",
        )

        repr_str = repr(identity)

        assert "OAuthIdentity" in repr_str
        assert str(identity_id) in repr_str
        assert "google" in repr_str
        assert str(account_id) in repr_str

    def test_oauth_identity_different_providers(self) -> None:
        """Test OAuthIdentity with different provider types."""
        account_id = uuid.uuid4()
        providers = ["google", "github", "microsoft", "linkedin"]

        for provider in providers:
            identity = OAuthIdentity(
                account_id=account_id,
                provider=provider,
                provider_user_id=f"{provider}_user_123",
            )
            assert identity.provider == provider
            assert identity.provider_user_id == f"{provider}_user_123"

    def test_oauth_identity_with_empty_raw_profile(self) -> None:
        """Test OAuthIdentity with empty raw_profile dict."""
        account_id = uuid.uuid4()

        identity = OAuthIdentity(
            account_id=account_id,
            provider="google",
            provider_user_id="123456789",
            raw_profile={},
        )

        assert identity.raw_profile == {}

    def test_oauth_identity_with_complex_raw_profile(self) -> None:
        """Test OAuthIdentity with nested raw_profile data."""
        account_id = uuid.uuid4()
        raw_profile = {
            "id": "123",
            "email": "test@example.com",
            "verified_email": True,
            "name": "Test User",
            "given_name": "Test",
            "family_name": "User",
            "picture": "https://example.com/photo.jpg",
            "locale": "en",
            "hd": "example.com",
            "metadata": {
                "scopes": ["email", "profile", "openid"],
                "token_info": {"issued_at": 1234567890},
            },
        }

        identity = OAuthIdentity(
            account_id=account_id,
            provider="google",
            provider_user_id="123456789",
            raw_profile=raw_profile,
        )

        assert identity.raw_profile == raw_profile
        assert identity.raw_profile is not None
        assert identity.raw_profile["metadata"]["scopes"] == ["email", "profile", "openid"]

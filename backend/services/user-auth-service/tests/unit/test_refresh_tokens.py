"""Unit tests for refresh_tokens module."""

from __future__ import annotations

import asyncio
import copy
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.testing import create_mock_session
from sqlalchemy.ext.asyncio import AsyncSession
from user_auth_service.core.refresh_tokens import (
    RefreshTokenData,
    RefreshTokenService,
    RevokedSession,
    generate_refresh_token,
    get_refresh_token_service,
    hash_refresh_token,
    init_refresh_token_service,
    verify_refresh_token_hash,
)
from user_auth_service.db.models import RefreshToken


class TestGenerateRefreshToken:
    """Tests for generate_refresh_token function."""

    def test_generates_token_with_correct_length(self) -> None:
        """Test that token has expected base64 length."""
        token, _ = generate_refresh_token()
        # 32 bytes = 256 bits, base64url encoding
        # Expected length is ceil(32 * 4/3) = 44 characters (with padding)
        assert len(token) == 44  # 32 bytes base64url-encoded

    def test_generates_unique_tokens(self) -> None:
        """Test that each call generates a unique token."""
        tokens = {generate_refresh_token()[0] for _ in range(100)}
        assert len(tokens) == 100  # All unique

    def test_token_is_url_safe(self) -> None:
        """Test that token uses URL-safe base64 encoding."""
        token, _ = generate_refresh_token()
        # URL-safe base64 uses - and _ instead of + and /, may have = padding
        assert "+" not in token
        assert "/" not in token
        assert all(c.isalnum() or c in "-_=" for c in token)

    def test_returns_token_and_token_id(self) -> None:
        """Test that function returns both token and token_id."""
        result = generate_refresh_token()
        assert isinstance(result, tuple)
        assert len(result) == 2
        token, token_id = result
        assert isinstance(token, str)
        assert isinstance(token_id, str)
        # token_id is first 16 bytes (32 hex chars)
        assert len(token_id) == 32
        assert all(c in "0123456789abcdef" for c in token_id)


class TestHashRefreshToken:
    """Tests for hash_refresh_token function."""

    @pytest.mark.asyncio
    async def test_hashes_token_with_argon2(self) -> None:
        """Test that token is hashed with Argon2id."""
        token = "test_token_123"
        hashed = await hash_refresh_token(token)
        assert hashed.startswith("$argon2id$")

    @pytest.mark.asyncio
    async def test_different_tokens_produce_different_hashes(self) -> None:
        """Test that different tokens produce different hashes."""
        token1 = "token_1"
        token2 = "token_2"
        hash1 = await hash_refresh_token(token1)
        hash2 = await hash_refresh_token(token2)
        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_same_token_produces_different_hashes(self) -> None:
        """Test that same token produces different hashes (salted)."""
        token = "same_token"
        hash1 = await hash_refresh_token(token)
        hash2 = await hash_refresh_token(token)
        # Argon2 uses random salt, so same input should produce different hashes
        assert hash1 != hash2


class TestVerifyRefreshTokenHash:
    """Tests for verify_refresh_token_hash function."""

    @pytest.mark.asyncio
    async def test_verifies_valid_hash(self) -> None:
        """Test that valid token/hash pair returns True."""
        token = "valid_token_123"
        token_hash = await hash_refresh_token(token)
        assert await verify_refresh_token_hash(token, token_hash) is True

    @pytest.mark.asyncio
    async def test_rejects_invalid_token(self) -> None:
        """Test that wrong token returns False."""
        token = "correct_token"
        wrong_token = "wrong_token"
        token_hash = await hash_refresh_token(token)
        assert await verify_refresh_token_hash(wrong_token, token_hash) is False

    @pytest.mark.asyncio
    async def test_handles_invalid_hash_format(self) -> None:
        """Test that invalid hash format returns False."""
        token = "any_token"
        invalid_hash = "not_a_valid_argon2_hash"
        assert await verify_refresh_token_hash(token, invalid_hash) is False

    @pytest.mark.asyncio
    async def test_handles_empty_hash(self) -> None:
        """Test that empty hash returns False."""
        token = "any_token"
        assert await verify_refresh_token_hash(token, "") is False

    @pytest.mark.asyncio
    async def test_handles_verify_mismatch_error(self) -> None:
        """Test handling of VerifyMismatchError (wrong token)."""
        # This is already tested by test_rejects_invalid_token
        # VerifyMismatchError is raised when token doesn't match hash
        token = "correct_token"
        wrong_token = "wrong_token"
        token_hash = await hash_refresh_token(token)
        # This internally catches VerifyMismatchError and returns False
        assert await verify_refresh_token_hash(wrong_token, token_hash) is False

    @pytest.mark.asyncio
    async def test_handles_invalid_hash_error(self) -> None:
        """Test handling of InvalidHashError (malformed hash)."""
        # This is already tested by test_handles_invalid_hash_format
        # InvalidHashError is raised when hash format is invalid
        token = "any_token"
        invalid_hash = "not_valid_argon2"
        # This internally catches InvalidHashError and returns False
        assert await verify_refresh_token_hash(token, invalid_hash) is False


class TestRefreshTokenData:
    """Tests for RefreshTokenData dataclass."""

    def test_creates_with_all_fields(self) -> None:
        """Test creating RefreshTokenData with all fields."""
        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=30)

        data = RefreshTokenData(
            account_id=account_id,
            session_family_id=session_family_id,
            expires_at=expires_at,
            created_at=now,
            is_revoked=True,
        )

        assert data.account_id == account_id
        assert data.session_family_id == session_family_id
        assert data.expires_at == expires_at
        assert data.created_at == now
        assert data.is_revoked is True


class TestRefreshTokenServiceCreateSession:
    """Tests for RefreshTokenService.create_session method."""

    @pytest.mark.asyncio
    async def test_creates_session_successfully(self) -> None:
        """Test creating a new session."""
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        account_id = uuid.uuid4()
        service = RefreshTokenService(expire_days=30)

        with (
            patch("user_auth_service.core.refresh_tokens.generate_refresh_token") as mock_gen,
            patch("user_auth_service.core.refresh_tokens.hash_refresh_token") as mock_hash,
            patch("user_auth_service.core.refresh_tokens.secrets.token_hex") as mock_token_hex,
        ):
            mock_gen.return_value = ("raw_token_123", "token_id_hex")
            mock_hash.return_value = "$argon2id$hashed"
            mock_token_hex.return_value = "a" * 32

            raw_token, session_family_id = await service.create_session(mock_db, account_id)

        assert raw_token == "raw_token_123"
        assert isinstance(session_family_id, uuid.UUID)
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()

        # Verify the RefreshToken was added with correct fields
        added_token = mock_db.add.call_args[0][0]
        assert isinstance(added_token, RefreshToken)
        assert added_token.account_id == account_id
        assert added_token.token_hash == "$argon2id$hashed"
        assert added_token.session_family_id == session_family_id

    @pytest.mark.asyncio
    async def test_new_sessions_for_same_account_use_different_families(self) -> None:
        mock_db = create_mock_session()
        service = RefreshTokenService(expire_days=30)
        account_id = uuid.uuid4()

        with (
            patch(
                "user_auth_service.core.refresh_tokens.generate_refresh_token",
                side_effect=[("raw-one", "id-one"), ("raw-two", "id-two")],
            ),
            patch("user_auth_service.core.refresh_tokens.hash_refresh_token", return_value="hash"),
            patch(
                "user_auth_service.core.refresh_tokens.secrets.token_hex",
                side_effect=["1" * 32, "2" * 32],
            ),
        ):
            _, first_family = await service.create_session(mock_db, account_id)
            _, second_family = await service.create_session(mock_db, account_id)

        assert first_family != second_family

    @pytest.mark.asyncio
    async def test_creates_session_with_correct_expiration(self) -> None:
        """Test that session has correct expiration time."""
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        account_id = uuid.uuid4()
        service = RefreshTokenService(expire_days=7)

        before_creation = datetime.now(UTC)

        with (
            patch("user_auth_service.core.refresh_tokens.generate_refresh_token") as mock_gen,
            patch("user_auth_service.core.refresh_tokens.hash_refresh_token") as mock_hash,
            patch("user_auth_service.core.refresh_tokens.secrets.token_hex") as mock_token_hex,
        ):
            mock_gen.return_value = ("raw_token", "token_id_hex")
            mock_hash.return_value = "$argon2id$hash"
            mock_token_hex.return_value = "a" * 32

            await service.create_session(mock_db, account_id)

        after_creation = datetime.now(UTC)

        added_token = mock_db.add.call_args[0][0]
        expected_expires_at_min = before_creation + timedelta(days=7)
        expected_expires_at_max = after_creation + timedelta(days=7)

        assert expected_expires_at_min <= added_token.expires_at <= expected_expires_at_max


class _ScalarResult:
    def __init__(self, token: RefreshToken | None) -> None:
        self._token = token

    def scalar_one_or_none(self) -> RefreshToken | None:
        return self._token


class _ConcurrentTokenStore:
    def __init__(self, token: RefreshToken) -> None:
        self.token = token
        self.row_lock = asyncio.Lock()
        self.unlocked_arrivals = 0
        self.unlocked_ready = asyncio.Event()
        self.family_revoked = False


class _RotationSession:
    """Minimal transaction fake that models PostgreSQL row-lock visibility."""

    def __init__(self, store: _ConcurrentTokenStore) -> None:
        self.store = store
        self.selected: RefreshToken | None = None
        self.owns_lock = False

    async def execute(self, statement: object) -> _ScalarResult:
        if getattr(statement, "is_select", False):
            if getattr(statement, "_for_update_arg", None) is not None:
                await self.store.row_lock.acquire()
                self.owns_lock = True
                self.selected = self.store.token
            else:
                self.store.unlocked_arrivals += 1
                if self.store.unlocked_arrivals == 2:
                    self.store.unlocked_ready.set()
                await self.store.unlocked_ready.wait()
                self.selected = copy.copy(self.store.token)
            return _ScalarResult(self.selected)

        self.store.family_revoked = True
        self.store.token.is_revoked = True
        return _ScalarResult(None)

    def add(self, _token: RefreshToken) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        if self.selected is not None and self.selected is not self.store.token:
            self.store.token.used_at = self.selected.used_at
        if self.owns_lock:
            self.store.row_lock.release()
            self.owns_lock = False


class TestRefreshTokenServiceRotateToken:
    """Tests for RefreshTokenService.rotate_token method."""

    @pytest.mark.asyncio
    async def test_rotates_token_successfully(self) -> None:
        """Test successful token rotation."""
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # Create a mock existing token
        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()
        existing_token = RefreshToken(
            id=uuid.uuid4(),
            account_id=account_id,
            token_id="abc123token_id_hex",
            token_hash="$argon2id$old_hash",
            session_family_id=session_family_id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_at=datetime.now(UTC),
            used_at=None,
            is_revoked=False,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_token
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService(expire_days=30)

        with (
            patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="abc123token_id_hex"),
            patch("user_auth_service.core.refresh_tokens.verify_refresh_token_hash", return_value=True),
            patch("user_auth_service.core.refresh_tokens.generate_refresh_token") as mock_gen,
            patch("user_auth_service.core.refresh_tokens.hash_refresh_token") as mock_hash,
        ):
            mock_gen.return_value = ("new_raw_token", "new_token_id_hex")
            mock_hash.return_value = "$argon2id$new_hash"

            result = await service.rotate_token(mock_db, "old_raw_token")

        assert result is not None
        assert isinstance(result, tuple)
        new_token, returned_account_id, returned_family_id = result
        assert new_token == "new_raw_token"
        assert returned_account_id == account_id
        assert returned_family_id == session_family_id
        assert existing_token.used_at is not None  # Old token marked as used
        mock_db.add.assert_called_once()  # New token added
        mock_db.flush.assert_awaited_once()
        rotated_token = mock_db.add.call_args.args[0]
        assert rotated_token.session_family_id == session_family_id

    @pytest.mark.asyncio
    async def test_rejects_expired_token(self) -> None:
        """Test that expired token returns None."""
        mock_db = create_mock_session()

        # Query filters out expired tokens, so we get None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService()

        with patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="valid_token_id"):
            result = await service.rotate_token(mock_db, "expired_token")

        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_revoked_token(self) -> None:
        """Test that revoked token returns None."""
        mock_db = create_mock_session()

        # Query filters out revoked tokens (is_revoked == False), so we get None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService()

        with patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="valid_token_id"):
            result = await service.rotate_token(mock_db, "revoked_token")

        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_non_matching_token(self) -> None:
        """Test that non-matching token returns None."""
        mock_db = create_mock_session()

        valid_token = RefreshToken(
            id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            token_id="valid_token_id",
            token_hash="$argon2id$hash",
            session_family_id=uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_at=datetime.now(UTC),
            used_at=None,
            is_revoked=False,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = valid_token
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService()

        with (
            patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="valid_token_id"),
            patch("user_auth_service.core.refresh_tokens.verify_refresh_token_hash", return_value=False),
        ):
            result = await service.rotate_token(mock_db, "wrong_token")

        assert result is None

    @pytest.mark.asyncio
    async def test_detects_token_reuse_and_revokes_family(self) -> None:
        """Test that reused token triggers session family revocation."""
        mock_db = create_mock_session()

        # Token that was already used
        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()
        used_token = RefreshToken(
            id=uuid.uuid4(),
            account_id=account_id,
            token_id="reused_token_id",
            token_hash="$argon2id$hash",
            session_family_id=session_family_id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_at=datetime.now(UTC) - timedelta(hours=1),
            used_at=datetime.now(UTC) - timedelta(minutes=5),  # Already used!
            is_revoked=False,
        )

        # First call returns the token, second call is the update
        mock_select_result = MagicMock()
        mock_select_result.scalar_one_or_none.return_value = used_token
        mock_update_result = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_select_result, mock_update_result])

        service = RefreshTokenService()

        with (
            patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="reused_token_id"),
            patch("user_auth_service.core.refresh_tokens.verify_refresh_token_hash", return_value=True),
        ):
            result = await service.rotate_token(mock_db, "reused_token")

        assert result == RevokedSession(account_id=account_id, session_family_id=session_family_id)
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_rotation_serializes_reuse_detection(self) -> None:
        """Two rotations of one token yield one successor and revoke the family."""
        stored_token = RefreshToken(
            id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            token_id="concurrent-token-id",
            token_hash="$argon2id$hash",
            session_family_id=uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_at=datetime.now(UTC),
            used_at=None,
            is_revoked=False,
        )
        store = _ConcurrentTokenStore(stored_token)
        sessions = (_RotationSession(store), _RotationSession(store))
        service = RefreshTokenService()

        async def rotate_and_commit(
            session: _RotationSession,
        ) -> tuple[str, uuid.UUID, uuid.UUID] | RevokedSession | None:
            result = await service.rotate_token(cast(AsyncSession, session), "same-raw-token")
            await session.commit()
            return result

        with (
            patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="concurrent-token-id"),
            patch("user_auth_service.core.refresh_tokens.verify_refresh_token_hash", return_value=True),
            patch(
                "user_auth_service.core.refresh_tokens.generate_refresh_token",
                return_value=("successor-token", "successor-token-id"),
            ),
            patch("user_auth_service.core.refresh_tokens.hash_refresh_token", return_value="$argon2id$successor"),
        ):
            results = await asyncio.gather(*(rotate_and_commit(session) for session in sessions))

        assert sum(isinstance(result, tuple) for result in results) == 1
        assert (
            results.count(
                RevokedSession(account_id=stored_token.account_id, session_family_id=stored_token.session_family_id)
            )
            == 1
        )
        assert store.family_revoked is True

    @pytest.mark.asyncio
    async def test_new_token_shares_session_family(self) -> None:
        """Test that rotated token shares same session family."""
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()
        existing_token = RefreshToken(
            id=uuid.uuid4(),
            account_id=account_id,
            token_id="existing_token_id",
            token_hash="$argon2id$old_hash",
            session_family_id=session_family_id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_at=datetime.now(UTC),
            used_at=None,
            is_revoked=False,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_token
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService(expire_days=30)

        with (
            patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="existing_token_id"),
            patch("user_auth_service.core.refresh_tokens.verify_refresh_token_hash", return_value=True),
            patch("user_auth_service.core.refresh_tokens.generate_refresh_token") as mock_gen,
            patch("user_auth_service.core.refresh_tokens.hash_refresh_token") as mock_hash,
        ):
            mock_gen.return_value = ("new_token", "new_token_id")
            mock_hash.return_value = "$argon2id$new_hash"

            await service.rotate_token(mock_db, "old_token")

        # Verify new token has same session_family_id
        added_token = mock_db.add.call_args[0][0]
        assert added_token.session_family_id == session_family_id


class TestRefreshTokenServiceRevokeSession:
    """Tests for RefreshTokenService.revoke_session method."""

    @pytest.mark.asyncio
    async def test_revokes_session_successfully(self) -> None:
        """Test successful session revocation."""
        mock_db = create_mock_session()

        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()
        token = RefreshToken(
            id=uuid.uuid4(),
            account_id=account_id,
            token_id="valid_token_id",
            token_hash="$argon2id$hash",
            session_family_id=session_family_id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_at=datetime.now(UTC),
            used_at=None,
            is_revoked=False,
        )

        mock_select_result = MagicMock()
        mock_select_result.scalar_one_or_none.return_value = token
        mock_update_result = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_select_result, mock_update_result])

        service = RefreshTokenService()

        with (
            patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="valid_token_id"),
            patch("user_auth_service.core.refresh_tokens.verify_refresh_token_hash", return_value=True),
        ):
            result = await service.revoke_session(mock_db, "raw_token")

        assert result is not None
        assert result.account_id == account_id
        assert result.session_family_id == session_family_id
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_none_for_non_existent_token(self) -> None:
        """Test that non-existent token returns no revoked session."""
        mock_db = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService()

        with patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="valid_token_id"):
            result = await service.revoke_session(mock_db, "non_existent_token")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_non_matching_token(self) -> None:
        """Test that a hash mismatch returns no revoked session."""
        mock_db = create_mock_session()

        token = RefreshToken(
            id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            token_id="valid_token_id",
            token_hash="$argon2id$hash",
            session_family_id=uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_at=datetime.now(UTC),
            used_at=None,
            is_revoked=False,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = token
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService()

        with (
            patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="valid_token_id"),
            patch("user_auth_service.core.refresh_tokens.verify_refresh_token_hash", return_value=False),
        ):
            result = await service.revoke_session(mock_db, "wrong_token")

        assert result is None

    @pytest.mark.asyncio
    async def test_skips_already_revoked_tokens(self) -> None:
        """Test that already revoked tokens return no revoked session."""
        mock_db = create_mock_session()

        # Only revoked tokens in DB (query filters is_revoked == False, so no results)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService()

        with patch("user_auth_service.core.refresh_tokens.extract_token_id", return_value="valid_token_id"):
            result = await service.revoke_session(mock_db, "any_token")

        assert result is None


class TestRefreshTokenServiceRevokeSessionFamily:
    """Tests for RefreshTokenService._revoke_session_family method."""

    @pytest.mark.asyncio
    async def test_revokes_all_tokens_in_family(self) -> None:
        """Test that all tokens in session family are revoked."""
        mock_db = create_mock_session()
        mock_execute_result = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_execute_result)

        session_family_id = uuid.uuid4()
        service = RefreshTokenService()

        await service._revoke_session_family(mock_db, session_family_id)

        # Verify update statement was executed
        mock_db.execute.assert_awaited_once()
        call_args = mock_db.execute.call_args[0][0]
        # Verify it's an update statement (has compile method)
        assert hasattr(call_args, "compile")

    @pytest.mark.asyncio
    async def test_revoke_session_family_cannot_cross_account_boundaries(self) -> None:
        """Family revocation updates only the authenticated account's family rows."""
        mock_db = create_mock_session()
        result = MagicMock(rowcount=1)
        mock_db.execute = AsyncMock(return_value=result)
        account_id = uuid.uuid4()
        session_family_id = uuid.uuid4()

        revoked = await RefreshTokenService().revoke_session_family(
            mock_db,
            account_id=account_id,
            session_family_id=session_family_id,
        )

        assert revoked == RevokedSession(account_id=account_id, session_family_id=session_family_id)
        statement = mock_db.execute.call_args.args[0]
        compiled = statement.compile()
        sql = str(compiled)
        assert "refresh_tokens.account_id =" in sql
        assert "refresh_tokens.session_family_id =" in sql
        assert account_id in compiled.params.values()
        assert session_family_id in compiled.params.values()


class TestRefreshTokenServiceCleanupExpired:
    """Tests for RefreshTokenService.cleanup_expired method."""

    @pytest.mark.asyncio
    async def test_deletes_expired_tokens(self) -> None:
        """Test that expired tokens are deleted."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService()
        deleted_count = await service.cleanup_expired(mock_db)

        assert deleted_count == 5
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_expired_tokens(self) -> None:
        """Test that zero is returned when no tokens are expired."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService()
        deleted_count = await service.cleanup_expired(mock_db)

        assert deleted_count == 0

    @pytest.mark.asyncio
    async def test_handles_none_rowcount(self) -> None:
        """Test handling when rowcount is None."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.rowcount = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = RefreshTokenService()
        deleted_count = await service.cleanup_expired(mock_db)

        assert deleted_count == 0


class TestGetRefreshTokenService:
    """Tests for get_refresh_token_service factory function."""

    def test_returns_singleton_instance(self) -> None:
        """Test that the same instance is returned on multiple calls."""
        # Reset singleton for clean test
        import user_auth_service.core.refresh_tokens as rt_module

        rt_module._RefreshTokenServiceHolder.instance = None

        service1 = get_refresh_token_service()
        service2 = get_refresh_token_service()

        assert service1 is service2
        assert isinstance(service1, RefreshTokenService)

        # Reset singleton after test
        rt_module._RefreshTokenServiceHolder.instance = None

    @pytest.mark.asyncio
    async def test_initialized_service_applies_configured_session_ttl(self) -> None:
        """The configured refresh lifetime controls persisted session expiry."""
        import user_auth_service.core.refresh_tokens as rt_module

        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        configured_days = 9
        init_refresh_token_service(configured_days)
        try:
            before_creation = datetime.now(UTC)
            with (
                patch(
                    "user_auth_service.core.refresh_tokens.generate_refresh_token",
                    return_value=("raw-token", "token-id"),
                ),
                patch(
                    "user_auth_service.core.refresh_tokens.hash_refresh_token",
                    return_value="$argon2id$hash",
                ),
            ):
                await get_refresh_token_service().create_session(mock_db, uuid.uuid4())
            after_creation = datetime.now(UTC)

            persisted = mock_db.add.call_args.args[0]
            assert before_creation + timedelta(days=configured_days) <= persisted.expires_at
            assert persisted.expires_at <= after_creation + timedelta(days=configured_days)
        finally:
            rt_module._RefreshTokenServiceHolder.instance = None

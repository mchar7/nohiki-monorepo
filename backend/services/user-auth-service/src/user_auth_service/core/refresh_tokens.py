"""Refresh token management with secure rotation and reuse detection.

Capabilities:
- Opaque refresh token generation (256-bit random)
- Argon2id hashing for storage
- Token rotation on every refresh
- Reuse detection (invalidates entire session family)
"""

from __future__ import annotations

import asyncio
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import argon2
from nohiki_observability import get_logger
from sqlalchemy import delete, select, update

from user_auth_service.db.models import RefreshToken

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Argon2id hasher for refresh tokens
_hasher = argon2.PasswordHasher(
    time_cost=2,
    memory_cost=19456,  # 19 MiB
    parallelism=1,
    hash_len=32,
    type=argon2.Type.ID,
)

# Refresh token configuration
REFRESH_TOKEN_BYTES = 32  # 256 bits
TOKEN_ID_BYTES = 16  # First 16 bytes used as lookup ID
REFRESH_TOKEN_EXPIRE_DAYS = 30


@dataclass(slots=True)
class RefreshTokenData:
    """Data associated with a refresh token."""

    account_id: UUID
    session_family_id: UUID
    expires_at: datetime
    created_at: datetime
    is_revoked: bool = False


@dataclass(frozen=True, slots=True)
class RevokedSession:
    """Identity of a refresh-token family revoked during logout."""

    account_id: UUID
    session_family_id: UUID


def generate_refresh_token() -> tuple[str, str]:
    """Generate a cryptographically secure refresh token with lookup ID.

    Returns:
        Tuple of (base64url-encoded token, hex-encoded token_id for lookup)

    """
    token_bytes = secrets.token_bytes(REFRESH_TOKEN_BYTES)
    token = urlsafe_b64encode(token_bytes).decode("ascii")
    token_id = token_bytes[:TOKEN_ID_BYTES].hex()
    return token, token_id


def extract_token_id(token: str) -> str | None:
    """Extract the token_id from a refresh token for database lookup.

    Args:
        token: The base64url-encoded refresh token

    Returns:
        Hex-encoded token_id or None if invalid format

    """
    try:
        token_bytes = urlsafe_b64decode(token.encode("ascii"))
        if len(token_bytes) < TOKEN_ID_BYTES:
            return None
        return token_bytes[:TOKEN_ID_BYTES].hex()
    except ValueError:
        return None


def _hash_refresh_token_sync(token: str) -> str:
    """Hash a refresh token using Argon2id (synchronous, CPU-bound)."""
    return _hasher.hash(token)


def _verify_refresh_token_hash_sync(token: str, token_hash: str) -> bool:
    """Verify a refresh token against its hash (synchronous, CPU-bound)."""
    try:
        _hasher.verify(token_hash, token)
    except argon2.exceptions.VerifyMismatchError:
        return False
    except argon2.exceptions.InvalidHashError:
        logger.warning("Invalid hash format encountered during verification")
        return False
    else:
        return True


async def hash_refresh_token(token: str) -> str:
    """Hash a refresh token using Argon2id, offloaded to a thread.

    Args:
        token: The raw refresh token

    Returns:
        Argon2id hash string

    """
    return await asyncio.to_thread(_hash_refresh_token_sync, token)


async def verify_refresh_token_hash(token: str, token_hash: str) -> bool:
    """Verify a refresh token against its hash, offloaded to a thread.

    Args:
        token: The raw refresh token to verify
        token_hash: The stored Argon2id hash

    Returns:
        True if token matches hash, False otherwise

    """
    return await asyncio.to_thread(_verify_refresh_token_hash_sync, token, token_hash)


class RefreshTokenService:
    """Service for managing refresh tokens with rotation and reuse detection.

    Session families:
    - Each login creates a new session family (UUID)
    - All refresh tokens from that session share the family ID
    - If a token is reused after rotation, the ENTIRE family is revoked
    """

    def __init__(self, expire_days: int = REFRESH_TOKEN_EXPIRE_DAYS) -> None:
        """Initialize the refresh token service."""
        self._expire_days = expire_days

    async def create_session(
        self,
        db: AsyncSession,
        account_id: UUID,
    ) -> tuple[str, UUID]:
        """Create a new session with a refresh token.

        Args:
            db: Database session
            account_id: Account's UUID

        Returns:
            Tuple of (raw_refresh_token, session_family_id)

        """
        session_family_id = UUID(secrets.token_hex(16))
        raw_token, token_id = generate_refresh_token()
        token_hash = await hash_refresh_token(raw_token)

        now = datetime.now(UTC)
        expires_at = now + timedelta(days=self._expire_days)

        refresh_token = RefreshToken(
            account_id=account_id,
            token_id=token_id,
            token_hash=token_hash,
            session_family_id=session_family_id,
            expires_at=expires_at,
            created_at=now,
        )

        db.add(refresh_token)
        await db.flush()

        logger.info(
            "Created new session",
            user_id=str(account_id),
            session_family_id=str(session_family_id),
        )

        return raw_token, session_family_id

    async def rotate_token(
        self,
        db: AsyncSession,
        old_token: str,
    ) -> tuple[str, UUID, UUID] | RevokedSession | None:
        """Rotate a refresh token (invalidate old, create new).

        This implements reuse detection:
        - If the token has already been rotated (used=True), revoke entire session family
        - Otherwise, mark as used and create new token

        Args:
            db: Database session
            old_token: The current refresh token

        Returns:
            Tuple for a successful rotation, RevokedSession on detected reuse, or None if invalid/revoked.

        """
        token_id = extract_token_id(old_token)
        if token_id is None:
            logger.warning("Invalid refresh token format")
            return None

        stmt = (
            select(RefreshToken)
            .where(
                RefreshToken.token_id == token_id,
                RefreshToken.is_revoked.is_(False),
                RefreshToken.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
        result = await db.execute(stmt)
        matched_token = result.scalar_one_or_none()

        if matched_token is None or not await verify_refresh_token_hash(old_token, matched_token.token_hash):
            logger.warning("Refresh token not found or expired")
            return None

        # Check if already used (reuse detection)
        if matched_token.used_at is not None:
            # SECURITY: Token reuse detected! Revoke entire session family
            logger.warning(
                "Refresh token reuse detected! Revoking session family",
                user_id=str(matched_token.account_id),
                session_family_id=str(matched_token.session_family_id),
            )
            await self._revoke_session_family(db, matched_token.session_family_id)
            return RevokedSession(
                account_id=matched_token.account_id, session_family_id=matched_token.session_family_id
            )

        # Mark current token as used
        matched_token.used_at = datetime.now(UTC)

        # Create new token in same session family
        new_raw_token, new_token_id = generate_refresh_token()
        new_token_hash = await hash_refresh_token(new_raw_token)
        now = datetime.now(UTC)

        new_refresh_token = RefreshToken(
            account_id=matched_token.account_id,
            token_id=new_token_id,
            token_hash=new_token_hash,
            session_family_id=matched_token.session_family_id,
            expires_at=now + timedelta(days=self._expire_days),
            created_at=now,
        )

        db.add(new_refresh_token)
        await db.flush()

        logger.debug(
            "Rotated refresh token",
            user_id=str(matched_token.account_id),
            session_family_id=str(matched_token.session_family_id),
        )

        return new_raw_token, matched_token.account_id, matched_token.session_family_id

    async def revoke_session(
        self,
        db: AsyncSession,
        token: str,
    ) -> RevokedSession | None:
        """Revoke a session (logout).

        Args:
            db: Database session
            token: The refresh token to revoke

        Returns:
            The revoked account and family, or None when the token is invalid.

        """
        token_id = extract_token_id(token)
        if token_id is None:
            return None
        stmt = select(RefreshToken).where(
            RefreshToken.token_id == token_id,
            RefreshToken.is_revoked.is_(False),
        )
        result = await db.execute(stmt)
        db_token = result.scalar_one_or_none()

        if db_token is None or not await verify_refresh_token_hash(token, db_token.token_hash):
            return None
        await self._revoke_session_family(db, db_token.session_family_id)
        logger.info(
            "Session revoked",
            user_id=str(db_token.account_id),
            session_family_id=str(db_token.session_family_id),
        )
        return RevokedSession(account_id=db_token.account_id, session_family_id=db_token.session_family_id)

    async def revoke_session_family(
        self,
        db: AsyncSession,
        *,
        account_id: UUID,
        session_family_id: UUID,
    ) -> RevokedSession | None:
        """Revoke a session family by its authenticated account and family claims."""
        stmt = (
            update(
                RefreshToken,
            )
            .where(
                RefreshToken.account_id == account_id,
                RefreshToken.session_family_id == session_family_id,
                RefreshToken.is_revoked.is_(False),
            )
            .values(is_revoked=True)
        )
        result = await db.execute(stmt)
        if getattr(result, "rowcount", 0) == 0:
            return None
        logger.info(
            "Session family revoked",
            user_id=str(account_id),
            session_family_id=str(session_family_id),
        )
        return RevokedSession(account_id=account_id, session_family_id=session_family_id)

    async def is_session_family_revoked(
        self,
        db: AsyncSession,
        *,
        account_id: UUID,
        session_family_id: UUID,
    ) -> bool:
        """Return whether the authenticated family has a persisted revocation."""
        stmt = (
            select(RefreshToken.id)
            .where(
                RefreshToken.account_id == account_id,
                RefreshToken.session_family_id == session_family_id,
                RefreshToken.is_revoked.is_(True),
            )
            .limit(1)
        )
        return await db.scalar(stmt) is not None

    async def _revoke_session_family(
        self,
        db: AsyncSession,
        session_family_id: UUID,
    ) -> None:
        """Revoke all tokens in a session family."""
        stmt = update(RefreshToken).where(RefreshToken.session_family_id == session_family_id).values(is_revoked=True)
        await db.execute(stmt)

    async def cleanup_expired(self, db: AsyncSession) -> int:
        """Clean up expired refresh tokens.

        Returns:
            Number of tokens deleted

        """
        stmt = delete(RefreshToken).where(
            RefreshToken.expires_at < datetime.now(UTC),
        )
        result = await db.execute(stmt)
        deleted: int = int(getattr(result, "rowcount", 0) or 0)
        if deleted:
            logger.info("Cleaned up expired refresh tokens", count=deleted)
        return deleted


class _RefreshTokenServiceHolder:
    """Singleton holder for RefreshTokenService."""

    instance: RefreshTokenService | None = None


def init_refresh_token_service(expire_days: int) -> RefreshTokenService:
    """Initialize the singleton with the configured token lifetime."""
    _RefreshTokenServiceHolder.instance = RefreshTokenService(expire_days=expire_days)
    return _RefreshTokenServiceHolder.instance


def get_refresh_token_service() -> RefreshTokenService:
    """Get the refresh token service singleton."""
    if _RefreshTokenServiceHolder.instance is None:
        _RefreshTokenServiceHolder.instance = RefreshTokenService()
    return _RefreshTokenServiceHolder.instance

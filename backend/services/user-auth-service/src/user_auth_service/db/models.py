"""Database models for user-auth-service (user-auth domain).

Schema: user_auth_schema
Tables: accounts, refresh_tokens, oauth_identities
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from nohiki_db_utils import SQL_NOW, UUID_DEFAULT, BaseEntity
from nohiki_db_utils.db_mixins import RepresentableMixin
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Schema name constant for easy reference
SCHEMA_NAME = "user_auth_schema"


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


class Account(BaseEntity, Base):
    """Account account for authentication."""

    __repr_fields__ = ("id", "email", "is_active")

    __tablename__ = "accounts"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    email: Mapped[str] = mapped_column(CITEXT, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("true"), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("false"), nullable=False)
    # BaseEntity provides: id (UUIDv7), created_at, updated_at

    oauth_identities: Mapped[list[OAuthIdentity]] = relationship(
        "OAuthIdentity",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def has_password(self) -> bool:
        """Check if account has a password set (vs OAuth-only)."""
        return self.hashed_password is not None


class RefreshToken(RepresentableMixin, Base):
    """Refresh token storage with session family tracking.

    Implements secure refresh token rotation with reuse detection:
    - Tokens are stored as Argon2id hashes (never plaintext)
    - session_family_id groups tokens from the same login session
    - used_at tracks when a token was rotated (for reuse detection)
    - If a used token is presented again, entire session family is revoked
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        sa.Index("ix_refresh_tokens_session_family", "session_family_id"),
        sa.Index("ix_refresh_tokens_account_id", "account_id"),
        sa.Index("ix_refresh_tokens_expires_at", "expires_at"),
        sa.Index("ix_refresh_tokens_token_id", "token_id"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(), primary_key=True, server_default=UUID_DEFAULT)
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(),
        sa.ForeignKey(f"{SCHEMA_NAME}.accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Token ID for direct lookup (first 16 bytes of token, hex-encoded)
    token_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # Argon2id hash of the refresh token (never store plaintext)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Session family ID for grouping tokens from the same login
    session_family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(), nullable=False)
    # Token lifecycle timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When this token was used (rotated) - NULL means not yet used
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Whether the entire session family has been revoked
    is_revoked: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("false"), nullable=False)

    __repr_fields__ = ("id", "account_id", "session_family_id")


class OAuthIdentity(RepresentableMixin, Base):
    """Represents a linked OAuth provider identity."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        UniqueConstraint("account_id", "provider", name="uq_oauth_account_provider"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(),
        primary_key=True,
        server_default=UUID_DEFAULT,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(),
        ForeignKey(f"{SCHEMA_NAME}.accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=SQL_NOW, nullable=False)

    account: Mapped[Account] = relationship("Account", back_populates="oauth_identities")

    __repr_fields__ = ("id", "provider", "account_id")

"""Account service for identity management."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from nohiki_fastapi_utils.errors import ConflictError, NotFoundError
from nohiki_observability import get_logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from user_auth_service.core.password import hash_password, verify_password
from user_auth_service.db.models import Account

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from user_auth_service.api.schemas import CreateUserRequest, UpdateUserRequest

logger = get_logger(__name__)


async def create_user(db: AsyncSession, user_create: CreateUserRequest) -> Account:
    """Create a new user."""
    # Check for existing email
    result = await db.execute(sa.select(Account).where(Account.email == user_create.email))
    if result.scalar_one_or_none():
        raise ConflictError(resource="Account", reason="Email already exists")

    hashed = await hash_password(user_create.password.get_secret_value())
    user = Account(
        email=user_create.email,
        hashed_password=hashed,
        display_name=user_create.display_name,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError(resource="Account", reason="Email already exists") from exc
    await db.refresh(user)

    logger.info("Created user", user_id=str(user.id), email=user.email)
    return user


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> Account:
    """Get user by ID."""
    user = await db.get(Account, user_id)
    if not user:
        raise NotFoundError(resource="Account", identifier=str(user_id))
    return user


async def get_user_by_email(db: AsyncSession, email: str) -> Account | None:
    """Get user by email."""
    result = await db.execute(select(Account).where(Account.email == email))
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, email: str, password: str) -> Account | None:
    """Authenticate user with email and password."""
    if not (user := await get_user_by_email(db, email)):
        return None
    if user.hashed_password is None:
        return None
    if not await verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        logger.warning("Auth attempt for inactive user", user_id=str(user.id))
        return None
    return user


# Fields that may be updated via the account PATCH endpoint.
# Explicit whitelist prevents mass-assignment of internal fields (e.g. is_active, is_verified).
_UPDATABLE_FIELDS: frozenset[str] = frozenset({"email", "first_name", "last_name", "display_name", "hashed_password"})


async def update_user(db: AsyncSession, user_id: UUID, user_update: UpdateUserRequest) -> Account:
    """Update user profile."""
    user = await get_user_by_id(db, user_id)
    update_data = user_update.model_dump(exclude_unset=True)

    if password := update_data.pop("password", None):
        update_data["hashed_password"] = await hash_password(password.get_secret_value())

    for field in _UPDATABLE_FIELDS:
        if field in update_data:
            setattr(user, field, update_data[field])

    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError(resource="Account", reason="Email already exists") from exc
    await db.refresh(user)
    logger.info("Updated user", user_id=str(user.id))
    return user


async def delete_user(db: AsyncSession, user_id: UUID) -> None:
    """Delete user."""
    user = await get_user_by_id(db, user_id)
    await db.delete(user)
    await db.flush()
    logger.info("Deleted user", user_id=str(user_id))

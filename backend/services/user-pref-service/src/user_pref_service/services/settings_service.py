"""Settings service for user preference settings management."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

from nohiki.common.v1 import EntityTimestamps, FeatureImportancePrefs
from nohiki.user.pref.v1 import (
    PrefFeatureImportanceUpdateRequested,
    UserPrefSettings,
    UserPrefSettingsUpdateRequested,
)
from nohiki_observability import get_logger
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from user_pref_service.db.models import SearchPref
from user_pref_service.db.models import UserPrefSettings as UserPrefSettingsModel
from user_pref_service.services.profile_service import get_profile_by_id

logger = get_logger(__name__)


def build_settings_snapshot(settings_model: UserPrefSettingsModel) -> UserPrefSettings:
    """Build a UserPrefSettings protobuf for ECST events."""
    created = settings_model.created_at
    updated = settings_model.updated_at

    if created is None or updated is None:
        msg = "settings created_at and updated_at must be set"
        raise ValueError(msg)

    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)

    return UserPrefSettings(
        user_id=str(settings_model.user_id),
        default_feature_importance=FeatureImportancePrefs.from_dict(settings_model.default_feature_importance)
        if settings_model.default_feature_importance
        else FeatureImportancePrefs(),
        preferred_timezone=settings_model.preferred_timezone,
        preferred_locale=settings_model.preferred_locale,
        timestamps=EntityTimestamps(created_at=created, updated_at=updated),
    )


async def get_user_settings(db: AsyncSession, user_id: UUID) -> UserPrefSettingsModel | None:
    """Get user preference settings by user_id."""
    result = await db.execute(select(UserPrefSettingsModel).where(UserPrefSettingsModel.user_id == user_id))
    return result.scalar_one_or_none()


async def delete_user_settings(db: AsyncSession, user_id: UUID) -> int:
    """Delete service-owned settings for an account."""
    result = await db.execute(delete(UserPrefSettingsModel).where(UserPrefSettingsModel.user_id == user_id))
    return getattr(result, "rowcount", 0) or 0


async def upsert_user_settings(
    db: AsyncSession,
    user_id: UUID,
    cmd: UserPrefSettingsUpdateRequested,
) -> tuple[UserPrefSettingsModel, bool]:
    """Upsert user preference settings from a command message.

    Returns tuple of (settings_model, is_new) where is_new is True if created.
    """
    updated_fields = set(cmd.updated_fields)

    values: dict[str, object] = {"user_id": user_id}

    if "default_feature_importance" in updated_fields:
        values["default_feature_importance"] = (
            cmd.default_feature_importance.to_dict() if cmd.default_feature_importance is not None else None
        )

    if "preferred_timezone" in updated_fields:
        values["preferred_timezone"] = cmd.preferred_timezone

    if "preferred_locale" in updated_fields:
        values["preferred_locale"] = cmd.preferred_locale

    existing = await get_user_settings(db, user_id)
    is_new = existing is None

    if is_new:
        stmt = insert(UserPrefSettingsModel).values(**values)
    else:
        update_values = {k: v for k, v in values.items() if k != "user_id"}
        stmt = (
            insert(UserPrefSettingsModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_=update_values,
            )
        )

    await db.execute(stmt)
    await db.flush()

    settings = await get_user_settings(db, user_id)
    if settings is None:
        msg = "Failed to upsert user settings"
        raise RuntimeError(msg)

    logger.info(
        "Upserted user settings",
        user_id=str(user_id),
        is_new=is_new,
    )
    return settings, is_new


async def update_profile_feature_importance(
    db: AsyncSession,
    pref_id: UUID,
    cmd: PrefFeatureImportanceUpdateRequested,
) -> SearchPref:
    """Update feature_importance for a specific search preference."""
    profile = await get_profile_by_id(db, pref_id)

    profile.feature_importance = cmd.feature_importance.to_dict() if cmd.feature_importance is not None else None
    await db.flush()

    updated_profile = await get_profile_by_id(db, pref_id)
    logger.info(
        "Updated profile feature importance",
        pref_id=str(pref_id),
        user_id=str(profile.user_id),
    )
    return updated_profile

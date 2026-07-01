"""User pref domain projection handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from betterproto2 import Casing
from nohiki.user.pref.v1 import (
    PrefCreated,
    PrefDeleted,
    PrefUpdated,
    UserPrefSettingsCreated,
    UserPrefSettingsUpdated,
)
from nohiki_common_exceptions import ValidationError
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from bff_service.core.kafka import kafka_client
from bff_service.db.models import ProfileProjection, UserPrefSettingsProjection
from bff_service.events.projections._constants import projection_priority_group_id
from bff_service.events.projections._helpers import (
    get_notification_threshold,
    percent_to_ratio,
)

logger = get_logger(__name__)


def _feature_importance(snapshot: object) -> dict[str, int] | None:
    prefs = getattr(snapshot, "feature_importance", None)
    if prefs is None:
        return None
    return {
        "skill_match_importance": prefs.skill_match_importance,
        "location_importance": prefs.location_importance,
        "work_arrangement_importance": prefs.work_arrangement_importance,
        "experience_importance": prefs.experience_importance,
        "salary_importance": prefs.salary_importance,
        "recency_importance": prefs.recency_importance,
    }


def _experience_preference(snapshot: object) -> dict[str, object] | None:
    preference = getattr(snapshot, "experience_preference", None)
    if preference is None:
        return None
    return {
        "experience_years": preference.experience_years,
        "seniority_levels": [level.name for level in preference.seniority_levels],
    }


@kafka_client.message_handler(
    Topics.USER_PREF_CREATED, PrefCreated, group_id=projection_priority_group_id, preserve_partition_order=False
)
@kafka_client.with_db_session()
async def handle_profile_created(message: PrefCreated, context: MessageContext) -> None:
    """Handle profile created event - create projection."""
    snapshot = message.pref_snapshot
    if snapshot is None:
        raise ValidationError(
            field_name="pref_snapshot",
            constraint="PrefCreated.pref_snapshot is required",
        )

    now = datetime.now(UTC)
    session = context.require_db_session()
    commute_preferences = (
        snapshot.commute_preferences.to_dict(casing=Casing.SNAKE) if snapshot.commute_preferences is not None else None
    )
    salary_preference = (
        snapshot.salary_preference.to_dict(casing=Casing.SNAKE) if snapshot.salary_preference is not None else None
    )
    stmt = (
        insert(ProfileProjection)
        .values(
            id=UUID(snapshot.id),
            user_id=UUID(snapshot.user_id),
            profile_name=snapshot.pref_name,
            search_keywords=list(snapshot.search_keywords),
            disallowed_keywords=list(snapshot.disallowed_keywords),
            work_arrangements=[arr.name for arr in snapshot.work_arrangements],
            user_skills=[entry.skill_id for entry in snapshot.user_skills],
            notification_threshold=get_notification_threshold(snapshot),
            auto_tailor_threshold=(
                percent_to_ratio(snapshot.auto_tailor_threshold) if snapshot.auto_tailor_threshold is not None else None
            ),
            tailoring_schema_id=snapshot.tailoring_schema_id or None,
            feature_importance=_feature_importance(snapshot),
            open_to_relocation=snapshot.open_to_relocation,
            commute_preferences=commute_preferences,
            salary_preference=salary_preference,
            experience_preference=_experience_preference(snapshot),
            is_active=snapshot.is_active,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "user_id": UUID(snapshot.user_id),
                "profile_name": snapshot.pref_name,
                "search_keywords": list(snapshot.search_keywords),
                "disallowed_keywords": list(snapshot.disallowed_keywords),
                "work_arrangements": [arr.name for arr in snapshot.work_arrangements],
                "user_skills": [entry.skill_id for entry in snapshot.user_skills],
                "notification_threshold": get_notification_threshold(snapshot),
                "auto_tailor_threshold": (
                    percent_to_ratio(snapshot.auto_tailor_threshold)
                    if snapshot.auto_tailor_threshold is not None
                    else None
                ),
                "tailoring_schema_id": snapshot.tailoring_schema_id or None,
                "feature_importance": _feature_importance(snapshot),
                "open_to_relocation": snapshot.open_to_relocation,
                "commute_preferences": commute_preferences,
                "salary_preference": salary_preference,
                "experience_preference": _experience_preference(snapshot),
                "is_active": snapshot.is_active,
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)
    logger.info("Profile projection created", pref_id=snapshot.id)


@kafka_client.message_handler(
    Topics.USER_PREF_UPDATED, PrefUpdated, group_id=projection_priority_group_id, preserve_partition_order=False
)
@kafka_client.with_db_session()
async def handle_profile_updated(message: PrefUpdated, context: MessageContext) -> None:
    """Handle profile updated event - upsert projection."""
    snapshot = message.pref_snapshot
    if snapshot is None:
        raise ValidationError(
            field_name="pref_snapshot",
            constraint="PrefUpdated.pref_snapshot is required",
        )

    now = datetime.now(UTC)
    session = context.require_db_session()
    commute_preferences = (
        snapshot.commute_preferences.to_dict(casing=Casing.SNAKE) if snapshot.commute_preferences is not None else None
    )
    salary_preference = (
        snapshot.salary_preference.to_dict(casing=Casing.SNAKE) if snapshot.salary_preference is not None else None
    )
    stmt = (
        insert(ProfileProjection)
        .values(
            id=UUID(snapshot.id),
            user_id=UUID(snapshot.user_id),
            profile_name=snapshot.pref_name,
            search_keywords=list(snapshot.search_keywords),
            disallowed_keywords=list(snapshot.disallowed_keywords),
            work_arrangements=[arr.name for arr in snapshot.work_arrangements],
            user_skills=[entry.skill_id for entry in snapshot.user_skills],
            notification_threshold=get_notification_threshold(snapshot),
            auto_tailor_threshold=(
                percent_to_ratio(snapshot.auto_tailor_threshold) if snapshot.auto_tailor_threshold is not None else None
            ),
            tailoring_schema_id=snapshot.tailoring_schema_id or None,
            feature_importance=_feature_importance(snapshot),
            open_to_relocation=snapshot.open_to_relocation,
            commute_preferences=commute_preferences,
            salary_preference=salary_preference,
            experience_preference=_experience_preference(snapshot),
            is_active=snapshot.is_active,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "profile_name": snapshot.pref_name,
                "search_keywords": list(snapshot.search_keywords),
                "disallowed_keywords": list(snapshot.disallowed_keywords),
                "work_arrangements": [arr.name for arr in snapshot.work_arrangements],
                "user_skills": [entry.skill_id for entry in snapshot.user_skills],
                "notification_threshold": get_notification_threshold(snapshot),
                "auto_tailor_threshold": (
                    percent_to_ratio(snapshot.auto_tailor_threshold)
                    if snapshot.auto_tailor_threshold is not None
                    else None
                ),
                "tailoring_schema_id": snapshot.tailoring_schema_id or None,
                "feature_importance": _feature_importance(snapshot),
                "open_to_relocation": snapshot.open_to_relocation,
                "commute_preferences": commute_preferences,
                "salary_preference": salary_preference,
                "experience_preference": _experience_preference(snapshot),
                "is_active": snapshot.is_active,
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)
    logger.info("Profile projection updated", pref_id=snapshot.id)


@kafka_client.message_handler(
    Topics.USER_PREF_DELETED, PrefDeleted, group_id=projection_priority_group_id, preserve_partition_order=False
)
@kafka_client.with_db_session()
async def handle_profile_deleted(message: PrefDeleted, context: MessageContext) -> None:
    """Handle profile deleted event - remove projection."""
    session = context.require_db_session()
    stmt = delete(ProfileProjection).where(ProfileProjection.id == UUID(message.pref_id))
    await session.execute(stmt)
    logger.info("Profile projection deleted", pref_id=message.pref_id)


@kafka_client.message_handler(
    Topics.USER_PREF_SETTINGS_CREATED,
    UserPrefSettingsCreated,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_user_pref_settings_created(message: UserPrefSettingsCreated, context: MessageContext) -> None:
    """Handle user pref settings created event - create projection."""
    settings_snapshot = message.settings
    if settings_snapshot is None:
        logger.warning("UserPrefSettingsCreated missing settings snapshot")
        return

    now = datetime.now(UTC)
    user_id = UUID(settings_snapshot.user_id)

    default_importance = None
    if settings_snapshot.default_feature_importance is not None:
        prefs = settings_snapshot.default_feature_importance
        default_importance = {
            "skill_match_importance": prefs.skill_match_importance,
            "location_importance": prefs.location_importance,
            "work_arrangement_importance": prefs.work_arrangement_importance,
            "experience_importance": prefs.experience_importance,
            "salary_importance": prefs.salary_importance,
            "recency_importance": prefs.recency_importance,
        }

    session = context.require_db_session()
    stmt = (
        insert(UserPrefSettingsProjection)
        .values(
            user_id=user_id,
            default_feature_importance=default_importance,
            preferred_timezone=settings_snapshot.preferred_timezone,
            preferred_locale=settings_snapshot.preferred_locale,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)
    logger.info("User pref settings projection created", user_id=str(user_id))


@kafka_client.message_handler(
    Topics.USER_PREF_SETTINGS_UPDATED,
    UserPrefSettingsUpdated,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_user_pref_settings_updated(message: UserPrefSettingsUpdated, context: MessageContext) -> None:
    """Handle user pref settings updated event - update projection."""
    settings_snapshot = message.settings
    if settings_snapshot is None:
        logger.warning("UserPrefSettingsUpdated missing settings snapshot")
        return

    now = datetime.now(UTC)
    user_id = UUID(settings_snapshot.user_id)

    default_importance = None
    if settings_snapshot.default_feature_importance is not None:
        prefs = settings_snapshot.default_feature_importance
        default_importance = {
            "skill_match_importance": prefs.skill_match_importance,
            "location_importance": prefs.location_importance,
            "work_arrangement_importance": prefs.work_arrangement_importance,
            "experience_importance": prefs.experience_importance,
            "salary_importance": prefs.salary_importance,
            "recency_importance": prefs.recency_importance,
        }

    session = context.require_db_session()
    stmt = (
        insert(UserPrefSettingsProjection)
        .values(
            user_id=user_id,
            default_feature_importance=default_importance,
            preferred_timezone=settings_snapshot.preferred_timezone,
            preferred_locale=settings_snapshot.preferred_locale,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "default_feature_importance": default_importance,
                "preferred_timezone": settings_snapshot.preferred_timezone,
                "preferred_locale": settings_snapshot.preferred_locale,
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)
    logger.info("User pref settings projection updated", user_id=str(user_id))

"""Profile service for CQRS operations - publishes commands, queries projections."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from nohiki.common.v1 import (
    ExperiencePreference,
    FeatureImportancePrefs,
    SalaryPreference,
    SearchPrefNotificationConfig,
    WorkArrangement,
)
from nohiki.user.pref.v1 import (
    PrefAttachUploadRequested,
    PrefCreateRequested,
    PrefDeleteRequested,
    PrefDetachUploadRequested,
    PrefFeatureImportanceUpdateRequested,
    PrefUpdateRequested,
    UserPrefSettingsUpdateRequested,
)
from nohiki_db_utils import create_event_metadata, paginate_query
from nohiki_kafka_client import Topics
from nohiki_observability import get_logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from uuid_utils.compat import uuid7

from bff_service.core.config import get_settings
from bff_service.core.kafka import kafka_client
from bff_service.db.models import CommandRequest, ProfileProjection, UserPrefSettingsProjection
from bff_service.services.models import CommandStatusDetail, ProfileDetail, ResolvedImportanceWeights

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
settings = get_settings()

_NEUTRAL_FEATURE_IMPORTANCE: int = 50


def _ratio_to_percent(value: float) -> int:
    """Convert 0-1 ratio to 0-100 percent."""
    return int(value * 100)


def _apply_update_lists(event: PrefUpdateRequested, data: dict[str, Any]) -> None:
    """Copy PATCH list fields onto the update event's repeated fields."""
    if "search_keywords" in data:
        event.search_keywords.extend(data["search_keywords"])
    if "disallowed_keywords" in data:
        event.disallowed_keywords.extend(data["disallowed_keywords"])
    if "user_skills" in data:
        event.user_skills.extend(data["user_skills"])
    if "work_arrangements" in data:
        event.work_arrangements.extend(WorkArrangement[w] for w in data["work_arrangements"])


def _apply_update_values(event: PrefUpdateRequested, data: dict[str, Any]) -> None:
    """Copy PATCH scalar and message fields onto the update event."""
    if "pref_name" in data:
        event.pref_name = data["pref_name"]
    if "auto_tailor_threshold" in data:
        event.auto_tailor_threshold = _ratio_to_percent(data["auto_tailor_threshold"])
    if "notification_threshold" in data:
        event.notification_config = SearchPrefNotificationConfig(
            threshold=_ratio_to_percent(data["notification_threshold"])
        )
    if "open_to_relocation" in data:
        event.open_to_relocation = data["open_to_relocation"]
    if salary_pref := data.get("salary_preference"):
        event.salary_preference = SalaryPreference.from_dict(salary_pref)
    if exp_pref := data.get("experience_preference"):
        event.experience_preference = ExperiencePreference.from_dict(exp_pref)


def _salary_preference_to_api(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rehydrate projected proto JSON and expose API-native scalar types."""
    if data is None:
        return None

    salary = SalaryPreference.from_dict(data)
    return {
        "min_salary": (
            {"minor_units": salary.min_salary.minor_units, "currency": salary.min_salary.currency}
            if salary.min_salary is not None
            else None
        ),
        "target_salary": (
            {"minor_units": salary.target_salary.minor_units, "currency": salary.target_salary.currency}
            if salary.target_salary is not None
            else None
        ),
        "preferred_frequency": salary.preferred_frequency,
    }


def _profile_to_detail(p: ProfileProjection) -> ProfileDetail:
    """Convert a ProfileProjection ORM instance to a typed ProfileDetail."""
    return ProfileDetail(
        id=str(p.id),
        user_id=str(p.user_id),
        pref_name=p.profile_name,
        search_keywords=p.search_keywords or [],
        disallowed_keywords=p.disallowed_keywords or [],
        work_arrangements=[str(w) for w in (p.work_arrangements or [])],
        user_skills=p.user_skills or [],
        notification_threshold=p.notification_threshold,
        auto_tailor_threshold=p.auto_tailor_threshold,
        open_to_relocation=p.open_to_relocation,
        salary_preference=_salary_preference_to_api(p.salary_preference),
        experience_preference=p.experience_preference,
        created_at=p.created_at.isoformat() if p.created_at else None,
        updated_at=p.updated_at.isoformat() if p.updated_at else None,
    )


class ProfileService:
    """Service for profile CQRS operations.

    Read operations query the projection database.
    Write operations publish command events to Kafka.
    """

    async def list_profiles(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[ProfileDetail], int]:
        """List one bounded page of a user's profiles from the projection DB."""
        stmt = (
            select(ProfileProjection)
            .where(ProfileProjection.user_id == user_id)
            .order_by(ProfileProjection.created_at.desc())
        )
        result = await paginate_query(db, stmt, offset=offset, limit=limit)
        return [_profile_to_detail(p) for p in result.items], result.total

    async def get_profile(self, db: AsyncSession, user_id: UUID, pref_id: UUID) -> ProfileDetail | None:
        """Get a specific profile from projection DB."""
        stmt = select(ProfileProjection).where(
            ProfileProjection.id == pref_id,
            ProfileProjection.user_id == user_id,
        )
        result = await db.execute(stmt)

        if profile := result.scalar_one_or_none():
            return _profile_to_detail(profile)
        return None

    async def create_profile_command(self, db: AsyncSession, user_id: UUID, data: dict[str, Any]) -> str:
        """Publish profile create command event."""
        request_id = str(uuid7())

        event = PrefCreateRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            user_id=str(user_id),
            pref_name=data.get("pref_name", ""),
            search_keywords=data.get("search_keywords", []),
            disallowed_keywords=data.get("disallowed_keywords", []),
            user_skills=data.get("user_skills", []),
            work_arrangements=[WorkArrangement[w] for w in data.get("work_arrangements", [])],
            is_active=True,
            open_to_relocation=data.get("open_to_relocation", False),
        )

        if (threshold := data.get("notification_threshold")) is not None:
            event.notification_config = SearchPrefNotificationConfig(threshold=_ratio_to_percent(threshold))

        if data.get("auto_tailor_threshold") is not None:
            event.auto_tailor_threshold = _ratio_to_percent(data["auto_tailor_threshold"])

        if salary_pref := data.get("salary_preference"):
            event.salary_preference = SalaryPreference.from_dict(salary_pref)

        if exp_pref := data.get("experience_preference"):
            event.experience_preference = ExperiencePreference.from_dict(exp_pref)

        await self._track_command(db, request_id, user_id, "create_profile")

        await kafka_client.publish(Topics.USER_PREF_CREATE_REQUESTED, event, key=request_id)

        logger.info("Published profile create command", user_id=str(user_id), request_id=request_id)
        return request_id

    async def update_profile_command(
        self,
        db: AsyncSession,
        user_id: UUID,
        pref_id: UUID,
        data: dict[str, Any],
    ) -> str:
        """Publish profile update command event."""
        request_id = str(uuid7())

        # consumer dispatch keys on event field names, not API keys
        updated_fields = ["notification_config" if f == "notification_threshold" else f for f in data]

        event = PrefUpdateRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            user_id=str(user_id),
            pref_id=str(pref_id),
            updated_fields=updated_fields,
        )

        _apply_update_lists(event, data)
        _apply_update_values(event, data)

        await self._track_command(db, request_id, user_id, "update_profile")

        await kafka_client.publish(Topics.USER_PREF_UPDATE_REQUESTED, event, key=request_id)

        logger.info(
            "Published profile update command",
            user_id=str(user_id),
            pref_id=str(pref_id),
            request_id=request_id,
        )
        return request_id

    async def delete_profile_command(self, user_id: UUID, pref_id: UUID) -> str:
        """Publish profile delete command event."""
        request_id = str(uuid7())

        event = PrefDeleteRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            user_id=str(user_id),
            pref_id=str(pref_id),
        )

        await kafka_client.publish(Topics.USER_PREF_DELETE_REQUESTED, event, key=request_id)

        logger.info(
            "Published profile delete command",
            user_id=str(user_id),
            pref_id=str(pref_id),
            request_id=request_id,
        )
        return request_id

    async def associate_attachment_command(self, user_id: UUID, pref_id: UUID, upload_id: UUID) -> str:
        """Publish attachment association command event."""
        request_id = str(uuid7())

        event = PrefAttachUploadRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            user_id=str(user_id),
            pref_id=str(pref_id),
            upload_id=str(upload_id),
        )

        await kafka_client.publish(Topics.USER_PREF_ATTACH_UPLOAD_REQUESTED, event, key=request_id)

        logger.info(
            "Published attach upload command",
            user_id=str(user_id),
            pref_id=str(pref_id),
            upload_id=str(upload_id),
            request_id=request_id,
        )
        return request_id

    async def disassociate_attachment_command(self, user_id: UUID, pref_id: UUID, upload_id: UUID) -> str:
        """Publish attachment disassociation command event."""
        request_id = str(uuid7())

        event = PrefDetachUploadRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            user_id=str(user_id),
            pref_id=str(pref_id),
            upload_id=str(upload_id),
        )

        await kafka_client.publish(Topics.USER_PREF_DETACH_UPLOAD_REQUESTED, event, key=request_id)

        logger.info(
            "Published detach upload command",
            user_id=str(user_id),
            pref_id=str(pref_id),
            upload_id=str(upload_id),
            request_id=request_id,
        )
        return request_id

    async def get_command_status(self, db: AsyncSession, user_id: UUID, request_id: UUID) -> CommandStatusDetail | None:
        """Get status of a command request."""
        stmt = select(CommandRequest).where(
            CommandRequest.request_id == request_id,
            CommandRequest.user_id == user_id,
        )
        result = await db.execute(stmt)

        if cmd := result.scalar_one_or_none():
            return CommandStatusDetail(
                request_id=str(cmd.request_id),
                command_type=cmd.command_type,
                status=cmd.status,
                created_at=cmd.created_at.isoformat() if cmd.created_at else None,
                completed_at=cmd.completed_at.isoformat() if cmd.completed_at else None,
                error_message=cmd.error_message,
            )
        return None

    async def _track_command(self, db: AsyncSession, request_id: str, user_id: UUID, command_type: str) -> None:
        """Track a command request for status polling."""
        stmt = insert(CommandRequest).values(
            request_id=UUID(request_id),
            user_id=user_id,
            command_type=command_type,
            status="pending",
            created_at=datetime.now(UTC),
        )
        await db.execute(stmt)
        await db.commit()

    async def set_default_feature_importance_command(
        self,
        user_id: UUID,
        importance_prefs: dict[str, Any],
    ) -> str:
        """Publish command to set user-level default feature importance preferences.

        These defaults apply to all search preferences unless overridden.
        """
        request_id = str(uuid7())

        feature_importance = FeatureImportancePrefs.from_dict(importance_prefs or {})

        event = UserPrefSettingsUpdateRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            user_id=str(user_id),
            default_feature_importance=feature_importance,
            updated_fields=["default_feature_importance"],
        )

        await kafka_client.publish(Topics.USER_PREF_SETTINGS_UPDATE_REQUESTED, event, key=request_id)

        logger.info(
            "Published user pref settings update command",
            user_id=str(user_id),
            request_id=request_id,
        )
        return request_id

    async def set_pref_feature_importance_command(
        self,
        user_id: UUID,
        pref_id: UUID,
        importance_prefs: dict[str, Any],
    ) -> str:
        """Publish command to set per-search-preference feature importance override.

        These override the user-level defaults for this specific search preference.
        """
        request_id = str(uuid7())

        feature_importance = FeatureImportancePrefs.from_dict(importance_prefs or {})

        event = PrefFeatureImportanceUpdateRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            user_id=str(user_id),
            pref_id=str(pref_id),
            feature_importance=feature_importance,
        )

        await kafka_client.publish(Topics.USER_PREF_FEATURE_IMPORTANCE_UPDATE_REQUESTED, event, key=request_id)

        logger.info(
            "Published pref feature importance update command",
            user_id=str(user_id),
            pref_id=str(pref_id),
            request_id=request_id,
        )
        return request_id

    async def get_resolved_importance(
        self,
        db: AsyncSession,
        user_id: UUID,
        pref_id: UUID,
    ) -> ResolvedImportanceWeights:
        """Get the resolved (merged) feature importance for a search preference.

        Resolution order:
        1. SearchPref.feature_importance (if set)
        2. UserPrefSettings.default_feature_importance (if set)
        3. Neutral defaults (50 for all fields)
        """
        profile_stmt = select(ProfileProjection).where(
            ProfileProjection.id == pref_id,
            ProfileProjection.user_id == user_id,
        )
        settings_stmt = select(UserPrefSettingsProjection).where(
            UserPrefSettingsProjection.user_id == user_id,
        )

        profile_result = await db.execute(profile_stmt)
        settings_result = await db.execute(settings_stmt)

        profile = profile_result.scalar_one_or_none()
        user_settings = settings_result.scalar_one_or_none()

        # Resolve the importance values
        pref_importance = getattr(profile, "feature_importance", None) if profile else None
        user_default_importance = user_settings.default_feature_importance if user_settings else None

        # Determine source
        if pref_importance and _has_any_importance_field(pref_importance):
            source = "search_pref"
            resolved = pref_importance
        elif user_default_importance and _has_any_importance_field(user_default_importance):
            source = "user_settings"
            resolved = user_default_importance
        else:
            source = "system_defaults"
            resolved = {}

        return ResolvedImportanceWeights(
            skill_match_importance=resolved.get("skill_match_importance", _NEUTRAL_FEATURE_IMPORTANCE),
            location_importance=resolved.get("location_importance", _NEUTRAL_FEATURE_IMPORTANCE),
            work_arrangement_importance=resolved.get("work_arrangement_importance", _NEUTRAL_FEATURE_IMPORTANCE),
            experience_importance=resolved.get("experience_importance", _NEUTRAL_FEATURE_IMPORTANCE),
            salary_importance=resolved.get("salary_importance", _NEUTRAL_FEATURE_IMPORTANCE),
            recency_importance=resolved.get("recency_importance", _NEUTRAL_FEATURE_IMPORTANCE),
            source=source,
        )


_IMPORTANCE_FIELDS = (
    "skill_match_importance",
    "location_importance",
    "work_arrangement_importance",
    "experience_importance",
    "salary_importance",
    "recency_importance",
)


def _has_any_importance_field(importance: dict[str, Any] | None) -> bool:
    """Check if any importance field is set."""
    if not importance:
        return False
    return any(importance.get(f) is not None for f in _IMPORTANCE_FIELDS)

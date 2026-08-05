"""Event publishing functions for profile lifecycle events."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from nohiki.user.pref.v1 import (
    PrefCreated,
    PrefDeleted,
    PrefEnrichmentFailed,
    PrefEnrichmentFailedFailureReason,
    PrefUpdated,
    UserPrefSettingsCreated,
    UserPrefSettingsUpdated,
)
from nohiki_db_utils import OutboxEventParams
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger

from user_pref_service.core.config import get_settings
from user_pref_service.services.profile_service import build_profile_snapshot, get_profile_by_id
from user_pref_service.services.settings_service import build_settings_snapshot

settings = get_settings()

if TYPE_CHECKING:
    from nohiki.skill.v1 import UserSkillEntry
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession

    from user_pref_service.db.models import PrefEnrichmentSaga, SearchPref
    from user_pref_service.db.models import UserPrefSettings as UserPrefSettingsModel

logger = get_logger(__name__)

AGGREGATE_TYPE = "profile"
SETTINGS_AGGREGATE_TYPE = "user_pref_settings"


class _BatchOutboxWriter(Protocol):
    async def write_events(
        self,
        db: AsyncSession | None,
        entries: Sequence[tuple[OutboxEventParams, PrefUpdated]],
    ) -> list[UUID]:
        """Write multiple profile events to the outbox table."""
        ...


def _build_profile_updated_request(
    profile: SearchPref,
    *,
    user_skills: list[UserSkillEntry] | None = None,
) -> tuple[OutboxEventParams, PrefUpdated]:
    """Build the outbox request for a profile updated event."""
    event = PrefUpdated(
        metadata=create_event_metadata(settings.service_name),
        pref_id=str(profile.id),
        user_id=str(profile.user_id),
        pref_snapshot=build_profile_snapshot(profile, user_skills=user_skills),
    )
    params = OutboxEventParams(
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=str(profile.id),
        event_type=Topics.USER_PREF_UPDATED,
    )
    return params, event


async def publish_profile_created_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    profile: SearchPref,
    *,
    user_skills: list[UserSkillEntry] | None = None,
) -> None:
    """Publish profile created event with SearchPrefSnapshot (ECST) via outbox."""
    await db.flush()
    fresh = await get_profile_by_id(db, profile.id)
    snapshot = build_profile_snapshot(fresh, user_skills=user_skills)

    event = PrefCreated(
        metadata=create_event_metadata(settings.service_name),
        pref_id=str(fresh.id),
        user_id=str(fresh.user_id),
        pref_snapshot=snapshot,
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=str(fresh.id),
            event_type=Topics.USER_PREF_CREATED,
        ),
        event=event,
    )
    logger.info("Published profile created event", pref_id=str(fresh.id))


async def publish_profile_updated_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    profile: SearchPref,
    *,
    user_skills: list[UserSkillEntry] | None = None,
) -> None:
    """Publish profile updated event with SearchPrefSnapshot (ECST) via outbox."""
    await db.flush()
    fresh = await get_profile_by_id(db, profile.id)
    params, event = _build_profile_updated_request(fresh, user_skills=user_skills)

    await outbox.write_event(db=db, params=params, event=event)
    logger.info("Published profile updated event", pref_id=str(fresh.id))


async def publish_profile_updated_batch(
    db: AsyncSession,
    outbox: OutboxWriter,
    profiles: Sequence[SearchPref],
    *,
    user_skills: list[UserSkillEntry] | None = None,
) -> None:
    """Publish a batch of profile updated events via outbox."""
    if not profiles:
        return

    await db.flush()
    await cast(_BatchOutboxWriter, outbox).write_events(
        db=db,
        entries=[_build_profile_updated_request(profile, user_skills=user_skills) for profile in profiles],
    )
    logger.info("Published profile updated events", count=len(profiles))


async def publish_profile_deleted_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    pref_id: UUID,
    user_id: UUID,
) -> None:
    """Publish profile deleted event via outbox."""
    event = PrefDeleted(
        metadata=create_event_metadata(settings.service_name),
        pref_id=str(pref_id),
        user_id=str(user_id),
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=str(pref_id),
            event_type=Topics.USER_PREF_DELETED,
        ),
        event=event,
    )
    logger.info("Published profile deleted event", pref_id=str(pref_id))


async def publish_pref_enrichment_failed(
    db: AsyncSession,
    outbox: OutboxWriter,
    saga: PrefEnrichmentSaga,
    *,
    reason: PrefEnrichmentFailedFailureReason,
    error_message: str,
) -> None:
    """Write a request-correlated terminal enrichment fact to the outbox."""
    event = PrefEnrichmentFailed(
        metadata=create_event_metadata(settings.service_name, saga.correlation_id),
        pref_id=str(saga.pref_id),
        user_id=str(saga.user_id),
        reason=reason,
        error_message=error_message,
        saga_id=str(saga.id),
        request_id=str(saga.request_id),
    )
    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=str(saga.pref_id),
            event_type=Topics.USER_PREF_ENRICHMENT_FAILED,
        ),
        event=event,
    )
    logger.warning(
        "Published terminal preference enrichment fact",
        saga_id=str(saga.id),
        request_id=str(saga.request_id),
        reason=reason.name,
    )


async def publish_settings_created_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    user_settings: UserPrefSettingsModel,
) -> None:
    """Publish user pref settings created event with full snapshot (ECST) via outbox."""
    event = UserPrefSettingsCreated(
        metadata=create_event_metadata(settings.service_name),
        user_id=str(user_settings.user_id),
        settings=build_settings_snapshot(user_settings),
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=SETTINGS_AGGREGATE_TYPE,
            aggregate_id=str(user_settings.user_id),
            event_type=Topics.USER_PREF_SETTINGS_CREATED,
        ),
        event=event,
    )
    logger.info("Published settings created event", user_id=str(user_settings.user_id))


async def publish_settings_updated_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    user_settings: UserPrefSettingsModel,
) -> None:
    """Publish user pref settings updated event with full snapshot (ECST) via outbox."""
    event = UserPrefSettingsUpdated(
        metadata=create_event_metadata(settings.service_name),
        user_id=str(user_settings.user_id),
        settings=build_settings_snapshot(user_settings),
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=SETTINGS_AGGREGATE_TYPE,
            aggregate_id=str(user_settings.user_id),
            event_type=Topics.USER_PREF_SETTINGS_UPDATED,
        ),
        event=event,
    )
    logger.info("Published settings updated event", user_id=str(user_settings.user_id))

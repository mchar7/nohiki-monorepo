"""Kafka event handlers for job-query-composition-service.

Handles user preference lifecycle events to maintain scrape query clustering:
- USER_PREF_CREATED: Add contributor, create/update query
- USER_PREF_UPDATED: Update contributor, recompute aggregates
- USER_PREF_DELETED: Remove contributor, delete query if last
- USER_ENTITLEMENT_CHANGED: Update frequency tier
- USER_AUTH_ACCOUNT_DELETED: Remove all contributions for user
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession

from nohiki.common.v1 import JobBoardSource, WorkArrangement
from nohiki.user.auth.v1 import AccountDeleted, UserActivity
from nohiki.user.entitlement.v1 import EntitlementChanged
from nohiki.user.pref.v1 import PrefCreated, PrefDeleted, PrefUpdated
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from job_query_composition_service.core.config import get_settings
from job_query_composition_service.core.kafka import kafka_client
from job_query_composition_service.events.publishers import (
    publish_queries_updated_batch,
    publish_query_created,
    publish_query_deleted,
    publish_query_deleted_batch,
    publish_query_updated,
)
from job_query_composition_service.services.aggregation import (
    recompute_query_aggregates,
    recompute_query_aggregates_batch,
)
from job_query_composition_service.services.query_service import (
    ContributorInput,
    create_or_update_contributor,
    delete_contributor,
    delete_query,
    delete_user_contributions,
    find_or_create_query,
    set_user_active,
    update_contributor_frequency,
)

logger = get_logger(__name__)
settings = get_settings()

DEFAULT_FREQUENCY_TIER = "daily"
MISSING_USER_ID_MSG = "Received message without user_id"

_TIER_TO_FREQUENCY: dict[str, str] = {
    "free": "daily",
    "pro": "hourly",
    "enterprise": "hourly",
}


async def _process_affected_queries(
    db: AsyncSession,
    outbox: OutboxWriter,
    query_ids: set[UUID],
) -> None:
    """Recompute and publish updates for affected queries.

    Uses batch fetch for O(1) database round-trip instead of O(N) individual fetches.
    """
    if not query_ids:
        return

    recomputed_queries = await recompute_query_aggregates_batch(db, query_ids)
    to_delete = [query_id for query_id, query in recomputed_queries.items() if query.total_contributor_count == 0]
    to_update = [query for query in recomputed_queries.values() if query.total_contributor_count > 0]

    if to_delete:
        await publish_query_deleted_batch(db, outbox, to_delete)
        for query_id in to_delete:
            await delete_query(db, query_id)

    if to_update:
        await publish_queries_updated_batch(db, outbox, to_update)


def _extract_frequency_tier(tier: str) -> str:
    """Map entitlements tier to frequency tier.

    Args:
        tier: Entitlements tier (free, pro, enterprise).

    Returns:
        Frequency tier (hourly, daily, weekly).

    """
    return _TIER_TO_FREQUENCY.get(tier.lower(), "daily")


@kafka_client.message_handler(
    Topics.USER_PREF_CREATED,
    PrefCreated,
    group_id=settings.kafka_consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_profile_created(
    message: PrefCreated,
    context: MessageContext,
) -> None:
    """Handle profile creation by adding contributor and creating/updating query."""
    snapshot = message.pref_snapshot
    if not snapshot or not snapshot.id:
        logger.warning("Received message without pref snapshot or ID", topic=Topics.USER_PREF_CREATED)
        return

    pref_id = UUID(snapshot.id)
    user_id = UUID(snapshot.user_id)

    logger.info("Processing user pref creation", pref_id=str(pref_id), user_id=str(user_id))
    locations = [loc.to_dict() for loc in snapshot.physical_locations] + [
        loc.to_dict() for loc in snapshot.remote_locations
    ]

    db = context.require_db_session()
    query = await find_or_create_query(db, list(snapshot.search_keywords), locations)
    is_new_query = query.total_contributor_count == 0

    await create_or_update_contributor(
        db,
        ContributorInput(
            query_id=query.id,
            pref_id=pref_id,
            user_id=user_id,
            work_arrangements=[v for v in snapshot.work_arrangements if v != WorkArrangement.UNSPECIFIED],
            locations=locations,
            sources=[v for v in snapshot.scrape_sources if v != JobBoardSource.UNSPECIFIED],
            frequency_tier=DEFAULT_FREQUENCY_TIER,
            is_active=snapshot.is_active and bool(snapshot.search_keywords),
        ),
    )

    recomputed = await recompute_query_aggregates(db, query.id)
    if not recomputed:
        return

    outbox = context.require_outbox()
    if is_new_query:
        await publish_query_created(db, outbox, recomputed)
    else:
        await publish_query_updated(db, outbox, recomputed)

    logger.info("Profile added to query", pref_id=str(pref_id), query_id=str(recomputed.id))


@kafka_client.message_handler(
    Topics.USER_PREF_UPDATED,
    PrefUpdated,
    group_id=settings.kafka_consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_profile_updated(
    message: PrefUpdated,
    context: MessageContext,
) -> None:
    """Handle user pref update by updating contributor and recomputing aggregates."""
    snapshot = message.pref_snapshot
    if not snapshot or not snapshot.id or not snapshot.user_id:
        logger.warning("Received incomplete preference snapshot", topic=Topics.USER_PREF_UPDATED)
        return

    pref_id = UUID(snapshot.id)
    user_id = UUID(snapshot.user_id)

    logger.info("Processing user pref update", pref_id=str(pref_id))
    locations = [loc.to_dict() for loc in snapshot.physical_locations] + [
        loc.to_dict() for loc in snapshot.remote_locations
    ]

    db = context.require_db_session()
    # Keywords/locations may have changed: find the matching query
    query = await find_or_create_query(db, list(snapshot.search_keywords), locations)

    is_new_query = query.total_contributor_count == 0
    contributor = await create_or_update_contributor(
        db,
        ContributorInput(
            query_id=query.id,
            pref_id=pref_id,
            user_id=user_id,
            work_arrangements=[v for v in snapshot.work_arrangements if v != WorkArrangement.UNSPECIFIED],
            locations=locations,
            sources=[v for v in snapshot.scrape_sources if v != JobBoardSource.UNSPECIFIED],
            frequency_tier=DEFAULT_FREQUENCY_TIER,
            is_active=snapshot.is_active and bool(snapshot.search_keywords),
        ),
    )
    previous_query_id = getattr(contributor, "previous_query_id", None)

    recomputed = await recompute_query_aggregates(db, query.id)
    if recomputed:
        outbox = context.require_outbox()
        if is_new_query:
            await publish_query_created(db, outbox, recomputed)
        else:
            await publish_query_updated(db, outbox, recomputed)

    if isinstance(previous_query_id, UUID):
        await _process_affected_queries(db, context.require_outbox(), {previous_query_id})


@kafka_client.message_handler(
    Topics.USER_PREF_DELETED,
    PrefDeleted,
    group_id=settings.kafka_consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_profile_deleted(
    message: PrefDeleted,
    context: MessageContext,
) -> None:
    """Handle user pref deletion by removing contributor and optionally deleting query."""
    if not message.pref_id:
        logger.warning("Received message without pref_id", topic=Topics.USER_PREF_DELETED)
        return

    pref_id = UUID(message.pref_id)
    logger.info("Processing user pref deletion", pref_id=str(pref_id))

    db = context.require_db_session()
    query_id, is_last = await delete_contributor(db, pref_id)

    if not query_id:
        logger.debug("Contributor not found, already deleted", pref_id=str(pref_id))
        return

    outbox = context.require_outbox()

    if is_last:
        await publish_query_deleted(db, outbox, query_id)
        await delete_query(db, query_id)
        logger.info("Deleted query (last contributor removed)", query_id=str(query_id))
    elif query := await recompute_query_aggregates(db, query_id):
        await publish_query_updated(db, outbox, query)


@kafka_client.message_handler(
    Topics.USER_ENTITLEMENT_CHANGED,
    EntitlementChanged,
    group_id=settings.kafka_consumer_group,
    preserve_partition_order=False,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_entitlements_changed(
    message: EntitlementChanged,
    context: MessageContext,
) -> None:
    """Handle entitlements change by updating frequency tier for user's contributions."""
    if not message.user_id:
        logger.warning(MISSING_USER_ID_MSG, topic=Topics.USER_ENTITLEMENT_CHANGED)
        return

    snapshot = message.entitlement_snapshot
    if not snapshot:
        logger.warning("Received entitlements change without snapshot", topic=Topics.USER_ENTITLEMENT_CHANGED)
        return

    user_id = UUID(message.user_id)
    frequency_tier = _extract_frequency_tier(snapshot.tier.name)

    logger.info("Processing entitlements change", user_id=str(user_id), tier=snapshot.tier)

    db = context.require_db_session()
    affected_query_ids = await update_contributor_frequency(db, user_id, frequency_tier)

    if affected_query_ids:
        updated_queries = await recompute_query_aggregates_batch(db, set(affected_query_ids))
        outbox = context.require_outbox()
        await publish_queries_updated_batch(db, outbox, updated_queries.values())


@kafka_client.message_handler(
    Topics.USER_AUTH_ACCOUNT_DELETED,
    AccountDeleted,
    group_id=settings.kafka_consumer_group,
    preserve_partition_order=False,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_user_deleted(
    message: AccountDeleted,
    context: MessageContext,
) -> None:
    """Handle user deletion by removing all their contributions."""
    if not message.user_id:
        logger.warning(MISSING_USER_ID_MSG, topic=Topics.USER_AUTH_ACCOUNT_DELETED)
        return

    user_id = UUID(message.user_id)
    logger.info("Processing account deletion", user_id=str(user_id))

    db = context.require_db_session()
    affected_query_ids = await delete_user_contributions(db, user_id)
    if not affected_query_ids:
        return

    await _process_affected_queries(db, context.require_outbox(), affected_query_ids)
    logger.info("Removed user contributions", user_id=str(user_id), queries_affected=len(affected_query_ids))


@kafka_client.message_handler(
    Topics.USER_AUTH_ACTIVITY,
    UserActivity,
    group_id=settings.kafka_consumer_group,
    preserve_partition_order=False,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_user_activity(
    message: UserActivity,
    context: MessageContext,
) -> None:
    """Handle user activity by reactivating inactive users."""
    if not message.user_id:
        logger.warning(MISSING_USER_ID_MSG, topic=Topics.USER_AUTH_ACTIVITY)
        return

    user_id = UUID(message.user_id)
    logger.debug("Processing account activity", user_id=str(user_id))

    db = context.require_db_session()
    affected_query_ids = await set_user_active(db, user_id)

    if affected_query_ids:
        updated_queries = await recompute_query_aggregates_batch(db, set(affected_query_ids))
        if updated_queries:
            outbox = context.require_outbox()
            await publish_queries_updated_batch(db, outbox, updated_queries.values())


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

"""Event handlers for job-ingest-schedule-service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from nohiki.common.v1 import JobBoardSource, WorkArrangement
from nohiki.job.ingest.v1 import IngestionQueryChanged, IngestionQueryDeleted
from nohiki.sys.v1 import ScheduleTick
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from job_ingest_schedule_service.core.config import get_settings
from job_ingest_schedule_service.core.kafka import kafka_client
from job_ingest_schedule_service.db.models import IngestionSchedule
from job_ingest_schedule_service.events.publishers import publish_scrape_triggered
from job_ingest_schedule_service.services.scheduler import process_due_schedules

logger = get_logger(__name__)

settings = get_settings()


class InvalidScheduleFrequencyError(ValueError):
    """Raised when an ingestion query carries a non-positive interval."""


def _validated_frequency(seconds: int) -> timedelta:
    """Validate the query-owned interval at the Kafka trust boundary."""
    if seconds <= 0:
        raise InvalidScheduleFrequencyError
    return timedelta(seconds=seconds)


@kafka_client.message_handler(
    Topics.SYS_SCHEDULE_TICK,
    ScheduleTick,
    group_id=f"{settings.kafka.consumer_group}-ticks",
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_schedule_tick(
    message: ScheduleTick,
    context: MessageContext,
) -> None:
    """Handle sys.fct.schedule-tick.v1 and trigger due schedules."""
    db = context.require_db_session()
    batch_limit = message.batch_limit if message.batch_limit > 0 else settings.scheduler.batch_limit
    triggered = await process_due_schedules(db, batch_limit=batch_limit)
    correlation_id = message.metadata.correlation_id if message.metadata else None
    logger.info(
        "Processed schedule tick",
        triggered=triggered,
        batch_limit=batch_limit,
        correlation_id=correlation_id,
    )


@kafka_client.message_handler(
    Topics.JOB_QUERY_CREATED,
    IngestionQueryChanged,
    group_id=settings.kafka.consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_query_created(
    message: IngestionQueryChanged,
    context: MessageContext,
) -> None:
    """Handle scrape_query.created.v1 event.

    Creates a new schedule record with denormalized query data.
    Sets next_run_at = NOW() if the query is active.
    """
    db = context.require_db_session()
    query_id = UUID(message.query_id)
    correlation_id = message.metadata.correlation_id if message.metadata else None
    logger.info(
        "Processing query created",
        query_id=str(query_id),
        correlation_id=correlation_id,
    )

    existing = await db.get(IngestionSchedule, query_id)
    if existing:
        logger.debug("Schedule already exists, skipping", query_id=str(query_id))
        return

    now = datetime.now(UTC)
    frequency = _validated_frequency(message.frequency_seconds)

    schedule = IngestionSchedule(
        query_id=query_id,
        search_keywords=list(message.search_keywords),
        locations=[
            {
                "country": loc.country.name,
                "location_type": loc.location_type.name,
                "state_province": loc.state_province,
                "city": loc.city,
            }
            for loc in message.locations
        ],
        work_arrangements=[wa for wa in message.work_arrangements if wa != WorkArrangement.UNSPECIFIED],
        remote_preferences=[],
        sources=[src for src in message.sources if src != JobBoardSource.UNSPECIFIED],
        frequency=frequency,
        is_active=message.is_active,
        next_run_at=now + frequency if message.is_active else None,
    )
    db.add(schedule)

    logger.info(
        "Created schedule",
        query_id=str(query_id),
        is_active=message.is_active,
        next_run_at=schedule.next_run_at.isoformat() if schedule.next_run_at else None,
    )

    if message.is_active:
        await publish_scrape_triggered(schedule, now)
        logger.info("Triggered immediate scrape for new query", query_id=str(query_id))


@kafka_client.message_handler(
    Topics.JOB_QUERY_UPDATED,
    IngestionQueryChanged,
    group_id=settings.kafka.consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_query_updated(
    message: IngestionQueryChanged,
    context: MessageContext,
) -> None:
    """Handle scrape_query.updated.v1 event.

    Updates existing schedule with new query parameters.
    If becoming active and no next_run_at, sets to NOW().
    """
    db = context.require_db_session()
    query_id = UUID(message.query_id)
    correlation_id = message.metadata.correlation_id if message.metadata else None
    logger.info(
        "Processing query updated",
        query_id=str(query_id),
        correlation_id=correlation_id,
    )

    schedule = await db.get(IngestionSchedule, query_id)

    if not schedule:
        logger.info("Schedule not found for update, creating", query_id=str(query_id))
        now = datetime.now(UTC)
        frequency = _validated_frequency(message.frequency_seconds)

        schedule = IngestionSchedule(
            query_id=query_id,
            search_keywords=list(message.search_keywords),
            locations=[
                {
                    "country": loc.country.name,
                    "location_type": loc.location_type.name,
                    "state_province": loc.state_province,
                    "city": loc.city,
                }
                for loc in message.locations
            ],
            work_arrangements=[wa for wa in message.work_arrangements if wa != WorkArrangement.UNSPECIFIED],
            remote_preferences=[],
            sources=[src for src in message.sources if src != JobBoardSource.UNSPECIFIED],
            frequency=frequency,
            is_active=message.is_active,
            next_run_at=now + frequency if message.is_active else None,
        )
        db.add(schedule)

        if message.is_active:
            await publish_scrape_triggered(schedule, now)
            logger.info("Triggered immediate scrape for new query (from update)", query_id=str(query_id))
        return

    now = datetime.now(UTC)
    was_active = schedule.is_active

    schedule.search_keywords = list(message.search_keywords)
    schedule.locations = [
        {
            "country": loc.country.name,
            "location_type": loc.location_type.name,
            "state_province": loc.state_province,
            "city": loc.city,
        }
        for loc in message.locations
    ]
    schedule.work_arrangements = [wa for wa in message.work_arrangements if wa != WorkArrangement.UNSPECIFIED]
    schedule.remote_preferences = []
    schedule.sources = [src for src in message.sources if src != JobBoardSource.UNSPECIFIED]
    schedule.frequency = _validated_frequency(message.frequency_seconds)
    schedule.is_active = message.is_active
    schedule.updated_at = now

    if message.is_active and not was_active:
        schedule.next_run_at = now + schedule.frequency
        await publish_scrape_triggered(schedule, now)
        logger.info("Queued immediate scrape for activated query", query_id=str(query_id))

    logger.info(
        "Updated schedule",
        query_id=str(query_id),
        is_active=message.is_active,
    )


@kafka_client.message_handler(
    Topics.JOB_QUERY_DELETED,
    IngestionQueryDeleted,
    group_id=settings.kafka.consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_query_deleted(
    message: IngestionQueryDeleted,
    context: MessageContext,
) -> None:
    """Handle scrape_query.deleted.v1 event.

    Removes the schedule record for the deleted query.
    """
    db = context.require_db_session()
    query_id = UUID(message.query_id)
    correlation_id = message.metadata.correlation_id if message.metadata else None
    logger.info(
        "Processing query deleted",
        query_id=str(query_id),
        correlation_id=correlation_id,
    )

    schedule = await db.get(IngestionSchedule, query_id)

    if not schedule:
        logger.debug("Schedule not found for deletion, already deleted", query_id=str(query_id))
        return

    await db.delete(schedule)
    logger.info("Deleted schedule", query_id=str(query_id))


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

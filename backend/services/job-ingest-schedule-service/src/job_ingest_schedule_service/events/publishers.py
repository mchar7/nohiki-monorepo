"""Event publishers for job-ingest-schedule-service."""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from nohiki.common.v1 import Location
from nohiki.job.ingest.v1 import IngestionQuery, IngestionTriggered
from nohiki_db_utils import create_event_metadata
from nohiki_kafka_client import Topics
from nohiki_observability import get_logger

from job_ingest_schedule_service.core.config import get_settings
from job_ingest_schedule_service.core.kafka import kafka_client
from job_ingest_schedule_service.db.models import IngestionSchedule

logger = get_logger(__name__)
settings = get_settings()


async def publish_scrape_triggered(
    schedule: IngestionSchedule,
    scheduled_for: datetime,
) -> None:
    """Publish one deterministic schedule-run command directly to Kafka."""
    run_id = str(uuid5(NAMESPACE_URL, f"{schedule.query_id}:{scheduled_for.isoformat()}"))
    metadata = create_event_metadata(settings.service_name, run_id)
    metadata.event_id = run_id
    metadata.timestamp = scheduled_for

    scrape_query = IngestionQuery(
        query_id=str(schedule.query_id),
        search_keywords=list(schedule.search_keywords),
        locations=[Location.from_dict(loc) for loc in schedule.locations],
        work_arrangements=schedule.work_arrangements,
        sources=schedule.sources,
        hours_old=schedule.hours_old,
        results_wanted=schedule.results_wanted,
    )

    event = IngestionTriggered(
        metadata=metadata,
        query=scrape_query,
    )

    await kafka_client.publish(
        topic=Topics.JOB_INGEST_DISCOVERY_REQUESTED,
        message=event,
        key=run_id,
    )

    logger.info(
        "Published scrape trigger",
        query_id=str(schedule.query_id),
        run_id=run_id,
        scheduled_for=scheduled_for.isoformat(),
        hours_old=schedule.hours_old,
        results_wanted=schedule.results_wanted,
    )

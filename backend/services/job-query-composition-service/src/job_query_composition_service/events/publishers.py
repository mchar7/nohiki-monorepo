"""Event publishers for job-query-composition-service."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, cast
from uuid import UUID

from nohiki.common.v1 import Location
from nohiki.job.ingest.v1 import (
    IngestionQueryChanged,
    IngestionQueryDeleted,
)
from nohiki_db_utils import OutboxEventParams, OutboxWriter, create_event_metadata
from nohiki_kafka_client import Topics
from nohiki_observability import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from job_query_composition_service.core.config import get_settings
from job_query_composition_service.db.models import IngestionQuery as DBIngestionQuery

logger = get_logger(__name__)
settings = get_settings()


class _BatchOutboxWriter(Protocol):
    async def write_events(
        self,
        db: AsyncSession | None,
        entries: Sequence[tuple[OutboxEventParams, object]],
    ) -> list[UUID]:
        """Write multiple query events to the outbox table."""
        ...


def _build_query_changed_request(
    query: DBIngestionQuery,
    event_type: str,
) -> tuple[OutboxEventParams, IngestionQueryChanged]:
    """Build the outbox request for a query changed event."""
    event = IngestionQueryChanged(
        metadata=create_event_metadata(settings.service_name, str(query.id)),
        query_id=str(query.id),
        search_keywords=list(query.search_keywords),
        locations=[Location.from_dict(loc) for loc in query.locations],
        work_arrangements=query.work_arrangements,
        sources=query.sources,
        frequency_seconds=int(query.frequency.total_seconds()),
        is_active=query.is_active,
    )
    params = OutboxEventParams(
        aggregate_type="ingestion_query",
        aggregate_id=str(query.id),
        event_type=event_type,
    )
    return params, event


async def publish_query_created(
    db: AsyncSession,
    outbox: OutboxWriter,
    query: DBIngestionQuery,
) -> None:
    """Publish query-created.v1 event via outbox for schedule service to consume."""
    params, event = _build_query_changed_request(query, Topics.JOB_QUERY_CREATED)

    await outbox.write_event(db=db, params=params, event=event)

    logger.info(
        "Published query-created.v1",
        query_id=str(query.id),
        keyword_count=len(query.search_keywords),
        work_arrangement_count=len(query.work_arrangements),
        source_count=len(query.sources),
    )


async def publish_query_updated(
    db: AsyncSession,
    outbox: OutboxWriter,
    query: DBIngestionQuery,
) -> None:
    """Publish query-updated.v1 event via outbox."""
    params, event = _build_query_changed_request(query, Topics.JOB_QUERY_UPDATED)

    await outbox.write_event(db=db, params=params, event=event)

    logger.info(
        "Published query-updated.v1",
        query_id=str(query.id),
    )


async def publish_query_deleted(
    db: AsyncSession,
    outbox: OutboxWriter,
    query_id: str | UUID,
) -> None:
    """Publish query-deleted.v1 event via outbox."""
    query_id_str = str(query_id)
    event = IngestionQueryDeleted(
        metadata=create_event_metadata(settings.service_name, query_id_str),
        query_id=query_id_str,
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type="ingestion_query",
            aggregate_id=query_id_str,
            event_type=Topics.JOB_QUERY_DELETED,
        ),
        event=event,
    )

    logger.info(
        "Published query-deleted.v1",
        query_id=query_id_str,
    )


async def publish_queries_updated_batch(
    db: AsyncSession,
    outbox: OutboxWriter,
    queries: Iterable[DBIngestionQuery],
) -> None:
    """Publish batch of query-updated.v1 events via outbox."""
    queries_list = list(queries)
    if not queries_list:
        return

    await cast("_BatchOutboxWriter", outbox).write_events(
        db=db,
        entries=[_build_query_changed_request(query, Topics.JOB_QUERY_UPDATED) for query in queries_list],
    )


async def publish_query_deleted_batch(
    db: AsyncSession,
    outbox: OutboxWriter,
    query_ids: Iterable[str | UUID],
) -> None:
    """Publish batch of query-deleted.v1 events via outbox."""
    query_id_list = [str(query_id) for query_id in query_ids]
    if not query_id_list:
        return

    await cast("_BatchOutboxWriter", outbox).write_events(
        db=db,
        entries=[
            (
                OutboxEventParams(
                    aggregate_type="ingestion_query",
                    aggregate_id=query_id,
                    event_type=Topics.JOB_QUERY_DELETED,
                ),
                IngestionQueryDeleted(
                    metadata=create_event_metadata(settings.service_name, query_id),
                    query_id=query_id,
                ),
            )
            for query_id in query_id_list
        ],
    )

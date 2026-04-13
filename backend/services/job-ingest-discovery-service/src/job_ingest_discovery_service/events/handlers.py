"""Kafka event handlers for job-ingest-discovery-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from uuid import NAMESPACE_URL, UUID, uuid5

from nohiki.job.ingest.v1 import IngestionTriggered
from nohiki_db_utils import check_and_mark_processed
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from job_ingest_discovery_service.core.config import get_settings
from job_ingest_discovery_service.core.kafka import kafka_client
from job_ingest_discovery_service.services.discovery_service import run_discovery

logger = get_logger(__name__)
settings = get_settings()


@kafka_client.message_handler(
    Topics.JOB_INGEST_DISCOVERY_REQUESTED,
    IngestionTriggered,
    group_id=settings.kafka.consumer_group,
    preserve_partition_order=False,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_discovery_triggered(
    message: IngestionTriggered,
    context: MessageContext,
) -> None:
    """Claim a discovery command until its at-least-once publication completes."""
    if not message.metadata:
        msg = "EventMetadata is required"
        raise ValueError(msg)
    if not message.query:
        msg = "IngestionQuery is required"
        raise ValueError(msg)

    query = message.query
    candidate = message.metadata.event_id or message.metadata.correlation_id
    try:
        run_id = str(UUID(candidate))
    except ValueError, AttributeError:
        run_id = str(uuid5(NAMESPACE_URL, f"{query.query_id}:{candidate}"))

    if isinstance(context, MessageContext):
        db = context.require_db_session()
        if not await check_and_mark_processed(
            db,
            settings.database.schema_name,
            run_id,
            handle_discovery_triggered.__name__,
        ):
            logger.info(
                "Discovery command already completed, skipping",
                query_id=query.query_id,
                discovery_id=run_id,
            )
            return

    logger.info(
        "Discovery triggered",
        query_id=query.query_id,
        discovery_id=run_id,
        keywords=list(query.search_keywords),
    )

    await run_discovery(query=query, discovery_id=run_id)

    logger.info("Discovery completed", query_id=query.query_id, discovery_id=run_id)


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

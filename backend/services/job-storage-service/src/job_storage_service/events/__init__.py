"""Event handlers and publishers for job-storage-service.

Publishers are available at module level for use by services.
Handlers are imported lazily in start_event_consumer() to avoid circular imports
with services that need publishers.
"""

from nohiki_observability import get_logger

from job_storage_service.core.config import get_settings
from job_storage_service.core.kafka import kafka_client
from job_storage_service.events.publishers import (
    OutboxContext,
    PublishContext,
    build_listing_snapshot,
    publish_listing_accepted_event,
    publish_listing_created_event,
    publish_listing_deleted_event,
    publish_listing_updated_event,
)

__all__ = [
    "OutboxContext",
    "PublishContext",
    "build_listing_snapshot",
    "publish_listing_accepted_event",
    "publish_listing_created_event",
    "publish_listing_deleted_event",
    "publish_listing_updated_event",
    "start_event_consumer",
]

logger = get_logger(__name__)
settings = get_settings()


def start_event_consumer() -> None:
    """Start the Kafka event consumer.

    Handlers are imported here to avoid circular imports with services that use publishers.
    The import triggers decorator registration of all message handlers.
    """
    from job_storage_service.events import backfill_handler, handlers, refresh_handler  # noqa: PLC0415

    _ = (handlers, backfill_handler, refresh_handler)  # Ensure handlers are registered
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

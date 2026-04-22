"""Event handlers for notification-service using decorator-based API.

Handles job correlation and content generation events for notifications.
"""

from nohiki.doc.content.v1 import ContentGenerationCompleted
from nohiki.job.correlation.v1 import CorrelationEvaluated
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from notification_service.core.config import get_settings
from notification_service.core.kafka import kafka_client
from notification_service.services.notification_handler import handle_notification_event
from notification_service.services.template_registry import (
    EVENT_TYPE_CONTENT_GENERATION_COMPLETED,
    EVENT_TYPE_CORRELATION_EVALUATED,
)

logger = get_logger(__name__)
settings = get_settings()


@kafka_client.message_handler(
    Topics.JOB_CORRELATION_EVALUATED,
    CorrelationEvaluated,
    group_id=settings.kafka.consumer_group,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_job_matched(
    message: CorrelationEvaluated,
    context: MessageContext,
) -> None:
    """Handle job correlation events for notifications."""
    await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, message, context)


@kafka_client.message_handler(
    Topics.DOC_CONTENT_GENERATION_COMPLETED,
    ContentGenerationCompleted,
    group_id=settings.kafka.consumer_group,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_content_generation_completed(
    message: ContentGenerationCompleted,
    context: MessageContext,
) -> None:
    """Handle content generation completed events for notifications."""
    await handle_notification_event(EVENT_TYPE_CONTENT_GENERATION_COMPLETED, message, context)


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

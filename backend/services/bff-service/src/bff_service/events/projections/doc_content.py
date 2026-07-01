"""Document content lifecycle projection handlers."""

from datetime import UTC, datetime
from uuid import UUID

from nohiki.doc.content.v1 import ContentGenerationCompleted, ContentGenerationFailed
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from redis.exceptions import RedisError
from sqlalchemy import update

from bff_service.core.kafka import kafka_client
from bff_service.db.models import DocumentGenerationStatus
from bff_service.events.projections._constants import projection_priority_group_id
from bff_service.sse import get_sse_bridge
from bff_service.sse.events import SSE_EVENT_DOCUMENT_STATUS, DocumentStatusPayload

logger = get_logger(__name__)


def _request_id(
    message: ContentGenerationCompleted | ContentGenerationFailed,
) -> UUID | None:
    """Return the request UUID only when event and metadata correlations agree."""
    correlation_id = message.metadata.correlation_id if message.metadata else None
    if not message.request_id or correlation_id != message.request_id:
        logger.warning(
            "Content generation event has inconsistent correlation",
            request_id=message.request_id,
            correlation_id=correlation_id,
        )
        return None
    try:
        return UUID(message.request_id)
    except ValueError:
        logger.warning(
            "Content generation event has invalid request_id",
            request_id=message.request_id,
        )
        return None


async def _publish_status(user_id: UUID, request_id: UUID, status: str, error_message: str | None = None) -> None:
    """Publish a projected lifecycle transition to the owning user's SSE channel."""
    try:
        await get_sse_bridge().publish(
            user_id,
            DocumentStatusPayload(
                type=SSE_EVENT_DOCUMENT_STATUS,
                request_id=str(request_id),
                status=status,
                error_message=error_message,
            ),
        )
    except OSError, RedisError, RuntimeError:
        logger.warning("SSE publish failed", request_id=str(request_id), exc_info=True)


@kafka_client.message_handler(
    Topics.DOC_CONTENT_GENERATION_COMPLETED,
    ContentGenerationCompleted,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session(auto_commit=False)
async def handle_content_generation_completed(
    message: ContentGenerationCompleted,
    context: MessageContext,
) -> None:
    """Project successful content generation as render work in progress."""
    request_id = _request_id(message)
    if request_id is None:
        return

    session = context.require_db_session()
    result = await session.execute(
        update(DocumentGenerationStatus)
        .where(
            DocumentGenerationStatus.request_id == request_id,
            DocumentGenerationStatus.job_correlation_id.is_not(None),
            DocumentGenerationStatus.status == "pending",
        )
        .values(status="in_progress")
        .returning(DocumentGenerationStatus.user_id)
    )
    user_id = result.scalar_one_or_none()
    await session.commit()
    if user_id is not None:
        await _publish_status(user_id, request_id, "in_progress")


@kafka_client.message_handler(
    Topics.DOC_CONTENT_GENERATION_FAILED,
    ContentGenerationFailed,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session(auto_commit=False)
async def handle_content_generation_failed(
    message: ContentGenerationFailed,
    context: MessageContext,
) -> None:
    """Project content failure as a terminal failed document request."""
    request_id = _request_id(message)
    if request_id is None:
        return

    error_message = (
        message.result.error.error_message
        if message.result and message.result.error and message.result.error.error_message
        else "Content generation failed"
    )
    session = context.require_db_session()
    result = await session.execute(
        update(DocumentGenerationStatus)
        .where(
            DocumentGenerationStatus.request_id == request_id,
            DocumentGenerationStatus.job_correlation_id.is_not(None),
            DocumentGenerationStatus.status.in_(("pending", "in_progress")),
        )
        .values(status="failed", error_message=error_message, completed_at=datetime.now(UTC))
        .returning(DocumentGenerationStatus.user_id)
    )
    user_id = result.scalar_one_or_none()
    await session.commit()
    if user_id is not None:
        await _publish_status(user_id, request_id, "failed", error_message)

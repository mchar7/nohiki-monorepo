"""ECST event publishers for doc-process-service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki.common.v1 import ErrorInfo
from nohiki.doc.process.v1 import (
    ProcessedDocumentSnapshot,
    ProcessingCallback,
    ProcessingResult,
)
from nohiki_kafka_client import callback_from_command, create_event_metadata
from nohiki_observability import get_logger

from doc_process_service.core.config import get_settings
from doc_process_service.core.kafka import kafka_client

if TYPE_CHECKING:
    from doc_process_service.events.types import ProcessingParams

logger = get_logger(__name__)
settings = get_settings()


async def publish_processing_completed(
    params: ProcessingParams,
    snapshot: ProcessedDocumentSnapshot,
) -> None:
    """Publish ProcessingCallback with success payload to callback_topic."""
    event = ProcessingCallback(
        metadata=create_event_metadata(
            settings.service_name,
            params.correlation_id,
        ),
        callback=callback_from_command(params.command),
        content_id=params.content_id,
        success=ProcessingResult(snapshot=snapshot),
    )

    await kafka_client.publish(params.command.callback_topic, event, key=params.command.operation_id)

    logger.info(
        "Published processing completed",
        operation_id=params.command.operation_id,
        content_id=params.content_id,
        topic=params.command.callback_topic,
    )


async def publish_processing_failed(
    params: ProcessingParams,
    error_code: str,
    error_message: str,
    *,
    is_retryable: bool,
) -> None:
    """Publish ProcessingCallback with error payload to callback_topic."""
    event = ProcessingCallback(
        metadata=create_event_metadata(
            settings.service_name,
            params.correlation_id,
        ),
        callback=callback_from_command(params.command),
        content_id=params.content_id,
        error=ErrorInfo(
            error_code=error_code,
            error_message=error_message,
            retryable=is_retryable,
        ),
    )

    await kafka_client.publish(params.command.callback_topic, event, key=params.command.operation_id)

    logger.info(
        "Published processing failed",
        operation_id=params.command.operation_id,
        content_id=params.content_id,
        error_code=error_code,
        is_retryable=is_retryable,
    )

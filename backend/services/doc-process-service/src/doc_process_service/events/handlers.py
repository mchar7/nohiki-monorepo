"""Kafka event handlers for document processing requests.

Handlers are registered at module import time via decorators.
This module should be imported by events_boot.py for side effects.
"""

from __future__ import annotations

import time
from functools import lru_cache
from uuid import UUID

from nohiki.doc.process.v1 import ProcessingLevel, ProcessingRequested
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from nohiki_s3_client import S3ObjectNotFoundError, S3ObjectTooLargeError, get_s3_client

from doc_process_service.cache import compute_content_hash
from doc_process_service.core.config import get_settings
from doc_process_service.core.kafka import kafka_client
from doc_process_service.events.publishers import (
    publish_processing_completed,
    publish_processing_failed,
)
from doc_process_service.events.types import ProcessingParams
from doc_process_service.metrics import DocProcessMetrics
from doc_process_service.models.domain import ProcessingOptions
from doc_process_service.services.processing import ProcessingService

logger = get_logger(__name__)

settings = get_settings()


@lru_cache(maxsize=1)
def _get_processing_service() -> ProcessingService:
    """Get singleton ProcessingService instance."""
    return ProcessingService(settings)


@kafka_client.message_handler(
    Topics.DOC_PROCESS_PROCESSING_REQUESTED,
    ProcessingRequested,
    group_id=settings.kafka_consumer_group,
)
async def handle_processing_requested(
    msg: ProcessingRequested,
    _ctx: MessageContext,
) -> None:
    """Handle document processing requests using ECST pattern.

    Args:
        msg: Processing request message from Kafka.
        _ctx: Message context (unused).

    """
    try:
        params = _build_processing_params(msg)
    except InvalidStorageKeyError as exc:
        # Invalid commands are terminal: acknowledge the poison message after
        # notifying the requester instead of allowing Kafka redelivery.
        params = _build_processing_params(msg, validate_storage_key=False)
        logger.warning(
            "Rejected processing request with invalid storage identity",
            operation_id=params.command.operation_id,
            content_id=msg.content_id,
            storage_key=msg.storage_key,
            error=str(exc),
        )
        await publish_processing_failed(
            params,
            error_code="INVALID_STORAGE_KEY",
            error_message=str(exc),
            is_retryable=False,
        )
        return

    logger.info(
        "Received processing request",
        operation_id=params.command.operation_id,
        storage_key=params.storage_key,
        content_id=params.content_id,
        processing_level=params.processing_level.name,
        correlation_id=params.correlation_id,
    )

    await _process_document(params)


class InvalidStorageKeyError(ValueError):
    """Raised when a processing request is not bound to its stored content."""


def _validate_storage_key(storage_key: str, content_id: str, user_id: str) -> None:
    """Require a canonical user-upload key bound to the command identities."""
    match storage_key.split("/"):
        case ["user-uploads", stored_user_id, stored_content_id, filename] if filename not in {
            "",
            ".",
            "..",
        }:
            pass
        case _:
            message = "storage_key must match user-uploads/{user_id}/{content_id}/{filename}"
            raise InvalidStorageKeyError(message)

    try:
        key_user_id = UUID(stored_user_id)
        requested_user_id = UUID(user_id)
        key_content_id = UUID(stored_content_id)
        requested_content_id = UUID(content_id)
    except ValueError as exc:
        message = "storage_key, user_id, and content_id identities must be UUIDs"
        raise InvalidStorageKeyError(message) from exc

    if key_user_id != requested_user_id:
        message = "storage_key user_id does not match requested user_id"
        raise InvalidStorageKeyError(message)

    if key_content_id != requested_content_id:
        message = "storage_key content_id does not match requested content_id"
        raise InvalidStorageKeyError(message)


def _build_processing_params(
    msg: ProcessingRequested,
    *,
    validate_storage_key: bool = True,
) -> ProcessingParams:
    """Build ProcessingParams from Kafka message.

    Args:
        msg: Processing request message.
        validate_storage_key: Whether to enforce storage identity binding.

    Returns:
        Processing parameters.

    """
    metadata = msg.metadata
    if validate_storage_key:
        _validate_storage_key(msg.storage_key, msg.content_id, msg.user_id)
    correlation_id = metadata.correlation_id if metadata and metadata.correlation_id else msg.command.operation_id

    return ProcessingParams(
        command=msg.command,
        storage_key=msg.storage_key,
        content_id=msg.content_id,
        processing_level=msg.processing_level or ProcessingLevel.BASIC,
        correlation_id=correlation_id,
    )


def _build_processing_options(level: ProcessingLevel) -> ProcessingOptions:
    """Build ProcessingOptions from processing level.

    Args:
        level: Requested processing level.

    Returns:
        Processing options configured for the level.

    """
    return ProcessingOptions(
        enable_ocr=level >= ProcessingLevel.OCR,
        extract_tables=level >= ProcessingLevel.TABLES,
        extract_images=level >= ProcessingLevel.IMAGES,
        enable_vlm_descriptions=level >= ProcessingLevel.FULL,
    )


async def _process_document(params: ProcessingParams) -> None:
    """Process document using ECST pattern.

    Fetches document from S3, processes via Docling, and publishes result.

    Args:
        params: Processing parameters.

    """
    metrics = DocProcessMetrics.get()
    metrics.record_request(params.processing_level.name, cached=False)

    s3 = get_s3_client(settings.s3)
    service = _get_processing_service()

    start = time.monotonic()

    try:
        raw_content = await s3.get_object(params.storage_key, max_bytes=settings.docling.max_document_bytes)
        content_hash = compute_content_hash(raw_content)
        options = _build_processing_options(params.processing_level)

        result = await service.process(params.content_id, raw_content, options)

        elapsed = time.monotonic() - start

        if result.success and result.content:
            result.content.content_hash = content_hash
            await publish_processing_completed(params, result.content)
            metrics.record_duration(elapsed, params.processing_level.name, success=True)
            logger.info(
                "Processing completed",
                operation_id=params.command.operation_id,
                content_id=params.content_id,
            )
        else:
            metrics.record_duration(elapsed, params.processing_level.name, success=False)
            metrics.record_error("processing_failed")
            await publish_processing_failed(
                params,
                error_code="PROCESSING_FAILED",
                error_message=result.error or "Unknown error",
                is_retryable=result.is_retryable,
            )

    except S3ObjectTooLargeError as e:
        elapsed = time.monotonic() - start
        metrics.record_duration(elapsed, params.processing_level.name, success=False)
        metrics.record_error("document_too_large")
        await publish_processing_failed(
            params,
            error_code="DOCUMENT_TOO_LARGE",
            error_message=str(e),
            is_retryable=False,
        )

    except S3ObjectNotFoundError as e:
        elapsed = time.monotonic() - start
        metrics.record_error("document_not_found")
        logger.warning(
            "Source document not found",
            operation_id=params.command.operation_id,
            storage_key=params.storage_key,
        )
        await publish_processing_failed(
            params,
            error_code="DOCUMENT_NOT_FOUND",
            error_message=str(e),
            is_retryable=False,
        )

    except (OSError, RuntimeError, ValueError) as e:
        elapsed = time.monotonic() - start
        metrics.record_error("internal_error")
        logger.exception(
            "Processing failed unexpectedly",
            operation_id=params.command.operation_id,
            error=str(e),
        )
        await publish_processing_failed(
            params,
            error_code="INTERNAL_ERROR",
            error_message=str(e),
            is_retryable=True,
        )
        raise


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

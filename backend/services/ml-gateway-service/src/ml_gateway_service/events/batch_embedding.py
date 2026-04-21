"""Batch embedding request handler for ML gateway.

Architecture: ml-gateway-service is ROUTING ONLY. This handler:
1. Receives batch embedding requests from ml.cmd.batch-embedding-requested.v1
2. Selects provider via registry (requires supports_batch_embedding)
3. Wraps in InternalComputeRequest and routes to provider's internal topic
4. Actual ML compute happens in ml-compute-service
"""

from __future__ import annotations

from nohiki.common.v1 import ErrorInfo
from nohiki.ml.v1 import (
    BatchEmbeddingCallback,
    BatchEmbeddingRequested,
    InternalComputeRequest,
    MlOperationType,
)
from nohiki_kafka_client import MessageContext, Topics, callback_from_command
from nohiki_observability import get_logger

from ml_gateway_service.core.config import get_settings
from ml_gateway_service.core.kafka import kafka_client
from ml_gateway_service.events.metadata import create_event_metadata
from ml_gateway_service.exceptions import NoProviderAvailableError
from ml_gateway_service.providers import get_provider_registry
from ml_gateway_service.providers.base import BaseMLProvider, MLOperationType

logger = get_logger(__name__)
settings = get_settings()


@kafka_client.message_handler(
    Topics.ML_BATCH_EMBEDDING_REQUESTED,
    BatchEmbeddingRequested,
    group_id=settings.kafka.consumer_group_batch_embedding,
    preserve_partition_order=False,
)
async def handle_batch_embedding_requested(
    message: BatchEmbeddingRequested,
    context: MessageContext,
) -> None:
    """Route batch embedding request to appropriate provider's internal topic."""
    del context
    try:
        provider = _get_provider_for_batch_embedding(message)
        item_count = len(message.items)
        batch_limit = provider.capabilities.max_batch_size
        if isinstance(batch_limit, int) and (item_count == 0 or item_count > batch_limit):
            await _publish_batch_failed(
                message,
                f"Batch size {item_count} must be between 1 and {batch_limit}",
                error_code="INVALID_BATCH_SIZE",
            )
            return
        await _route_to_provider(message, provider)
    except NoProviderAvailableError:
        await _publish_batch_failed(
            message,
            "No ML provider available for batch embedding operation",
            error_code="NO_PROVIDER",
        )


def _get_provider_for_batch_embedding(message: BatchEmbeddingRequested) -> BaseMLProvider:
    """Select provider that supports batch embedding."""
    registry = get_provider_registry()
    provider = registry.get_provider_for_operation(
        MLOperationType.BATCH_EMBEDDING,
        require_gpu=False,
    )

    if provider is None:
        logger.error(
            "No provider available for batch embedding",
            operation_id=message.command.operation_id,
            entity_type=message.entity_type.name,
            item_count=len(message.items),
        )
        operation = "batch_embedding"
        raise NoProviderAvailableError(operation)

    return provider


async def _route_to_provider(
    message: BatchEmbeddingRequested,
    provider: BaseMLProvider,
) -> None:
    """Wrap request in InternalComputeRequest and publish to provider topic."""
    target_topic = provider.get_target_topic(MLOperationType.BATCH_EMBEDDING)

    metadata = message.metadata
    if metadata is None:
        msg = "BatchEmbeddingRequested.metadata is required but was None"
        raise ValueError(msg)

    internal_request = InternalComputeRequest(
        metadata=create_event_metadata(metadata.correlation_id),
        operation_type=MlOperationType.BATCH_EMBEDDING,
        batch_embedding_request=message,
        selected_provider=provider.name,
        retry_attempt=0,
    )

    await kafka_client.publish(
        topic=target_topic,
        message=internal_request,
        key=message.command.operation_id,
    )

    logger.info(
        "Routed batch embedding request to provider",
        operation_id=message.command.operation_id,
        item_count=len(message.items),
        provider=provider.name,
        target_topic=target_topic,
    )


async def _publish_batch_failed(
    message: BatchEmbeddingRequested,
    error: str,
    error_code: str,
) -> None:
    """Publish BatchEmbeddingFailed to callback topic."""
    metadata = message.metadata
    if metadata is None:
        msg = "BatchEmbeddingRequested.metadata is required but was None"
        raise ValueError(msg)

    failed = BatchEmbeddingCallback(
        metadata=create_event_metadata(metadata.correlation_id),
        callback=callback_from_command(message.command),
        entity_type=message.entity_type,
        collection_version=message.collection_version,
        encoding_mode=message.encoding_mode,
        error=ErrorInfo(error_code=error_code, error_message=error, retryable=False),
    )
    await kafka_client.publish(
        topic=message.command.callback_topic,
        message=failed,
        key=message.command.operation_id,
    )

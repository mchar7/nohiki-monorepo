"""Embedding request handler for ML gateway.

Architecture: ml-gateway-service is ROUTING ONLY. This handler:
1. Receives embedding requests from ml.cmd.embedding-requested.v1
2. Selects provider via registry based on operation type
3. Routes to provider-specific internal topic (ml.internal.k8s-compute.v1 or ml.internal.modal-compute.v1)
4. Actual ML compute happens in ml-compute-service or Modal functions

The handler does NOT execute ML inference - it only routes requests.
"""

from __future__ import annotations

from nohiki.common.v1 import ErrorInfo
from nohiki.ml.v1 import (
    EmbeddingCallback,
    EmbeddingRequested,
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
    Topics.ML_EMBEDDING_REQUESTED,
    EmbeddingRequested,
    group_id=settings.kafka.consumer_group_embedding,
    preserve_partition_order=False,
)
async def handle_embedding_requested(
    message: EmbeddingRequested,
    context: MessageContext,
) -> None:
    """Route embedding request to appropriate provider's internal topic.

    This handler does NOT execute ML inference. It:
    1. Selects the best provider for embeddings (typically Kubernetes)
    2. Wraps the original request in InternalComputeRequest
    3. Publishes to the provider's internal topic
    4. ml-compute-service or Modal functions handle actual ML compute
    """
    del context  # Not needed for routing
    try:
        provider = _get_provider_for_embedding(message)
        await _route_to_provider(message, provider)
    except NoProviderAvailableError:
        await _publish_embedding_failed(
            message,
            "No ML provider available for embedding operation",
        )
        raise


def _get_provider_for_embedding(message: EmbeddingRequested) -> BaseMLProvider:
    """Get provider for embedding operation."""
    registry = get_provider_registry()

    # Embeddings don't require GPU - prefer Kubernetes (cost-effective)
    provider = registry.get_provider_for_operation(
        MLOperationType.EMBEDDING,
        require_gpu=False,
    )

    if provider is None:
        logger.error(
            "No provider available for embedding",
            operation_id=message.command.operation_id,
            entity_id=message.entity_id,
        )
        operation = "embedding"
        raise NoProviderAvailableError(operation)

    logger.debug(
        "Selected provider for embedding",
        operation_id=message.command.operation_id,
        entity_id=message.entity_id,
        provider=provider.name,
    )
    return provider


async def _route_to_provider(
    message: EmbeddingRequested,
    provider: BaseMLProvider,
) -> None:
    """Route request to provider's internal Kafka topic."""
    target_topic = provider.get_target_topic(MLOperationType.EMBEDDING)

    metadata = message.metadata
    if metadata is None:
        msg = "EmbeddingRequested.metadata is required but was None"
        raise ValueError(msg)

    correlation_id = metadata.correlation_id

    internal_request = InternalComputeRequest(
        metadata=create_event_metadata(correlation_id),
        operation_type=MlOperationType.EMBEDDING,
        embedding_request=message,
        selected_provider=provider.name,
        retry_attempt=0,
    )

    await kafka_client.publish(
        topic=target_topic,
        message=internal_request,
        key=message.command.operation_id,
    )

    logger.info(
        "Routed embedding request to provider",
        operation_id=message.command.operation_id,
        entity_id=message.entity_id,
        provider=provider.name,
        target_topic=target_topic,
    )


async def _publish_embedding_failed(
    message: EmbeddingRequested,
    error: str,
) -> None:
    """Publish embedding failed event to callback topic."""
    metadata = message.metadata
    if metadata is None:
        msg = "EmbeddingRequested.metadata is required but was None"
        raise ValueError(msg)

    correlation_id = metadata.correlation_id

    failed = EmbeddingCallback(
        metadata=create_event_metadata(correlation_id),
        callback=callback_from_command(message.command),
        entity_id=message.entity_id,
        entity_type=message.entity_type,
        error=ErrorInfo(error_code="NO_PROVIDER", error_message=error, retryable=True),
    )
    await kafka_client.publish(
        topic=message.command.callback_topic,
        message=failed,
        key=message.command.operation_id,
    )

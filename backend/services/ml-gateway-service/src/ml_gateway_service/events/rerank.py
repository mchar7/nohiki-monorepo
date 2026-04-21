"""Rerank request handler for ML gateway.

Architecture: Gateway is ROUTING ONLY. It receives requests, selects a provider,
and forwards to the provider's internal Kafka topic. The compute worker does
actual ML work and publishes completion events directly.
"""

from __future__ import annotations

from nohiki.common.v1 import ErrorInfo
from nohiki.ml.v1 import (
    InternalComputeRequest,
    MlOperationType,
    RerankCallback,
    RerankRequested,
)
from nohiki_kafka_client import MessageContext, Topics, callback_from_command
from nohiki_observability import get_logger

from ml_gateway_service.core.config import get_settings
from ml_gateway_service.core.kafka import kafka_client
from ml_gateway_service.events.metadata import create_event_metadata
from ml_gateway_service.exceptions import NoProviderAvailableError
from ml_gateway_service.providers import get_provider_registry
from ml_gateway_service.providers.base import BaseMLProvider
from ml_gateway_service.providers.base import MLOperationType as ProviderOpType

logger = get_logger(__name__)
settings = get_settings()


@kafka_client.message_handler(
    Topics.ML_RERANK_REQUESTED,
    RerankRequested,
    group_id=settings.kafka.consumer_group_rerank,
    preserve_partition_order=False,
)
async def handle_rerank_requested(
    message: RerankRequested,
    context: MessageContext,
) -> None:
    """Route rerank request to appropriate provider's internal topic."""
    try:
        provider = _get_provider_or_fail(message)
        await _route_to_provider(message, context, provider)
    except NoProviderAvailableError:
        await _publish_routing_failed(
            message,
            "No ML provider available for rerank operation",
        )
        raise


def _get_provider_or_fail(message: RerankRequested) -> BaseMLProvider:
    """Get provider that supports reranking or raise NoProviderAvailableError."""
    registry = get_provider_registry()
    provider = registry.get_provider_for_operation(
        ProviderOpType.RERANK,
        require_gpu=True,  # Reranking needs GPU
    )

    if provider is None:
        logger.error(
            "No provider available for reranking",
            operation_id=message.command.operation_id,
        )
        msg = "rerank"
        raise NoProviderAvailableError(msg)

    logger.info(
        "Routing rerank to provider",
        operation_id=message.command.operation_id,
        provider=provider.name,
        num_documents=len(message.documents),
    )
    return provider


async def _route_to_provider(
    message: RerankRequested,
    _context: MessageContext,
    provider: BaseMLProvider,
) -> None:
    """Route request to provider's internal Kafka topic.

    The compute worker will handle actual ML work and publish completion.
    """
    target_topic = provider.get_target_topic(ProviderOpType.RERANK)

    correlation_id = message.metadata.correlation_id if message.metadata else None
    internal_request = InternalComputeRequest(
        metadata=create_event_metadata(correlation_id),
        selected_provider=provider.name,
        operation_type=MlOperationType.RERANK,
        rerank_request=message,
    )

    await kafka_client.publish(
        topic=target_topic,
        message=internal_request,
        key=message.command.operation_id,
    )

    logger.info(
        "Routed rerank to internal topic",
        operation_id=message.command.operation_id,
        provider=provider.name,
        topic=target_topic,
    )


async def _publish_routing_failed(
    message: RerankRequested,
    error: str,
) -> None:
    """Publish routing failure callback to the requester's callback topic."""
    correlation_id = message.metadata.correlation_id if message.metadata else None
    failed = RerankCallback(
        metadata=create_event_metadata(correlation_id),
        callback=callback_from_command(message.command),
        error=ErrorInfo(error_code="NO_PROVIDER", error_message=error, retryable=True),
    )
    await kafka_client.publish(
        topic=message.command.callback_topic,
        message=failed,
        key=message.command.operation_id,
    )

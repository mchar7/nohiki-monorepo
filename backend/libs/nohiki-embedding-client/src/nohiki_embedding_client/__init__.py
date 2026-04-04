"""Unified embedding publisher for Nohiki services.

Fire-and-forget publisher for requesting
ML embeddings via Kafka events. Callbacks arrive asynchronously
on service-specific callback topics and are handled by dedicated
Kafka message handlers: fully compatible with multi-pod K8s.

Usage:
    from nohiki_embedding_client import EmbeddingPublisher, EmbeddingResult

    publisher = EmbeddingPublisher(
        callback_topic="my-service.sys.embedding-callback.v1",
        service_name="my-service",
        collection_version="v1",
    )

    # Fire-and-forget publish
    operation_id = await publisher.request_embedding(
        text="Software Engineer with Python experience",
        entity_id="skill-123",
        entity_type=EntityType.SKILL,
        spec=EmbeddingSpec(requested_types=[EmbeddingType.DENSE]),
    )

    # Callback handler (registered separately in events_boot.py)
    @kafka_client.message_handler(
        topic="my-service.sys.embedding-callback.v1",
        message_type=EmbeddingCallback,
        group_id="my-service-embedding-callback-primary",
    )
    async def handle_embedding_callback(msg, ctx):
        result = EmbeddingResult.from_callback(msg)
        ...

"""

from nohiki_embedding_client.exceptions import (
    EmbeddingError,
    EmbeddingFailedError,
)
from nohiki_embedding_client.publisher import EmbeddingPublisher
from nohiki_embedding_client.types import BatchEmbeddingItemResult, EmbeddingResult, EmbeddingSpec

__all__ = [
    "BatchEmbeddingItemResult",
    "EmbeddingError",
    "EmbeddingFailedError",
    "EmbeddingPublisher",
    "EmbeddingResult",
    "EmbeddingSpec",
]

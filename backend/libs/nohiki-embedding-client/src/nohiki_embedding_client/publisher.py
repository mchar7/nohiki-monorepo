"""Fire-and-forget embedding request publisher."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from nohiki.common.v1 import CommandHeader
from nohiki.ml.v1 import BatchEmbeddingRequested, EmbeddingRequested
from nohiki_kafka_client import CommandContext, Topics, create_event_metadata, get_kafka_client
from nohiki_observability import get_logger
from uuid_utils import uuid7

from nohiki_embedding_client.types import EmbeddingSpec

if TYPE_CHECKING:
    from nohiki.ml.v1 import BatchEmbeddingItem, EncodingMode, EntityType

logger = get_logger(__name__)

_DEFAULT_CONTEXT = CommandContext()


class EmbeddingPublisher:
    """Fire-and-forget embedding request publisher.

    Publishes EmbeddingRequested or BatchEmbeddingRequested commands to Kafka
    and returns immediately. Callbacks arrive asynchronously on the service's
    callback topic and are handled by dedicated Kafka message handlers.

    """

    def __init__(
        self,
        callback_topic: str,
        service_name: str,
        collection_version: str,
    ) -> None:
        """Initialize the embedding publisher.

        Args:
            callback_topic: Kafka topic for receiving responses.
            service_name: Name of the service using this publisher.
            collection_version: Qdrant collection version (e.g., "v1").

        """
        self._callback_topic = callback_topic
        self._service_name = service_name
        self._collection_version = collection_version

    @property
    def callback_topic(self) -> str:
        """Return the callback topic for this publisher."""
        return self._callback_topic

    @property
    def service_name(self) -> str:
        """Return the service name."""
        return self._service_name

    @property
    def collection_version(self) -> str:
        """Return the collection version."""
        return self._collection_version

    async def request_embedding(
        self,
        *,
        text: str,
        entity_id: str,
        entity_type: EntityType,
        spec: EmbeddingSpec,
        context: CommandContext = _DEFAULT_CONTEXT,
    ) -> str:
        """Publish EmbeddingRequested command (fire-and-forget).

        Builds CommandHeader with operation_id (UUIDv7), callback_topic,
        caller_context, and attributes. Returns operation_id for logging.

        Args:
            text: Text content to embed.
            entity_id: Unique identifier for the entity.
            entity_type: Type of entity being embedded.
            spec: Embedding specification (types, mode, indexing).
            context: Command context with caller_context and attributes.

        Returns:
            The operation_id (UUIDv7 string) for logging/correlation.

        Raises:
            RuntimeError: If Kafka client is not initialized.

        """
        operation_id = str(uuid7())

        request = EmbeddingRequested(
            metadata=create_event_metadata(source_service=self._service_name),
            command=CommandHeader(
                operation_id=operation_id,
                callback_topic=self._callback_topic,
                caller_context=context.caller_context,
                attributes=context.attributes,
            ),
            entity_id=entity_id,
            entity_type=entity_type,
            text=text,
            collection_version=self._collection_version,
            requested_types=list(spec.requested_types),
            encoding_mode=spec.encoding_mode,
            publish_to_index=spec.publish_to_index,
        )

        await get_kafka_client().publish(
            topic=Topics.ML_EMBEDDING_REQUESTED,
            message=request,
            key=entity_id,
        )

        logger.debug(
            "Published embedding request",
            operation_id=operation_id,
            entity_id=entity_id,
            entity_type=entity_type,
            callback_topic=self._callback_topic,
        )

        return operation_id

    async def request_batch_embedding(
        self,
        *,
        items: Sequence[BatchEmbeddingItem],
        entity_type: EntityType,
        encoding_mode: EncodingMode,
        context: CommandContext = _DEFAULT_CONTEXT,
    ) -> str:
        """Publish BatchEmbeddingRequested command (fire-and-forget).

        Args:
            items: Batch of text items to embed.
            entity_type: Type of entities being embedded.
            encoding_mode: How to encode (DOCUMENT or QUERY).
            context: Command context with caller_context and attributes.

        Returns:
            The operation_id (UUIDv7 string) for logging/correlation.

        Raises:
            RuntimeError: If Kafka client is not initialized.
            ValueError: If items sequence is empty.

        """
        if not items:
            msg = "Batch embedding items must not be empty"
            raise ValueError(msg)

        operation_id = str(uuid7())

        request = BatchEmbeddingRequested(
            metadata=create_event_metadata(source_service=self._service_name),
            command=CommandHeader(
                operation_id=operation_id,
                callback_topic=self._callback_topic,
                caller_context=context.caller_context,
                attributes=context.attributes,
            ),
            entity_type=entity_type,
            collection_version=self._collection_version,
            encoding_mode=encoding_mode,
            items=list(items),
        )

        await get_kafka_client().publish(
            topic=Topics.ML_BATCH_EMBEDDING_REQUESTED,
            message=request,
            key=operation_id,
        )

        logger.debug(
            "Published batch embedding request",
            operation_id=operation_id,
            item_count=len(items),
            entity_type=entity_type,
            callback_topic=self._callback_topic,
        )

        return operation_id

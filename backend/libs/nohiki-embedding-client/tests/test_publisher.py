"""Tests for nohiki_embedding_client.publisher module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from nohiki.ml.v1 import (
    BatchEmbeddingItem,
    BatchEmbeddingRequested,
    EmbeddingRequested,
    EmbeddingType,
    EncodingMode,
    EntityType,
)
from nohiki_embedding_client.publisher import EmbeddingPublisher
from nohiki_embedding_client.types import EmbeddingSpec
from nohiki_kafka_client import CommandContext, Topics


@pytest.fixture
def publisher() -> EmbeddingPublisher:
    """Create an EmbeddingPublisher for testing."""
    return EmbeddingPublisher(
        callback_topic="test.sys.embedding-callback.v1",
        service_name="test-service",
        collection_version="v1",
    )


@pytest.fixture
def mock_kafka_client() -> AsyncMock:
    """Create a mock Kafka client."""
    client = AsyncMock()
    client.publish = AsyncMock()
    return client


class TestEmbeddingPublisherInit:
    """Tests for EmbeddingPublisher initialization."""

    def test_properties(self, publisher: EmbeddingPublisher) -> None:
        """Properties return constructor values."""
        assert publisher.callback_topic == "test.sys.embedding-callback.v1"
        assert publisher.service_name == "test-service"
        assert publisher.collection_version == "v1"


class TestRequestEmbedding:
    """Tests for EmbeddingPublisher.request_embedding."""

    @pytest.mark.anyio
    async def test_publishes_to_correct_topic(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """Publishes EmbeddingRequested to ML_EMBEDDING_REQUESTED topic."""
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            await publisher.request_embedding(
                text="Software Engineer with Python",
                entity_id="550e8400-e29b-41d4-a716-446655440000",
                entity_type=EntityType.JOB,
                spec=EmbeddingSpec(
                    requested_types=[EmbeddingType.DENSE],
                    encoding_mode=EncodingMode.DOCUMENT,
                ),
            )

        mock_kafka_client.publish.assert_called_once()
        call_kwargs = mock_kafka_client.publish.call_args.kwargs
        assert call_kwargs["topic"] == Topics.ML_EMBEDDING_REQUESTED
        assert call_kwargs["key"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.anyio
    async def test_builds_command_header(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """Builds CommandHeader with operation_id, callback_topic, caller_context."""
        context = CommandContext(
            caller_context=b'{"test": true}',
            attributes={"role": "retrieval"},
        )
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            operation_id = await publisher.request_embedding(
                text="Software Engineer with Python",
                entity_id="550e8400-e29b-41d4-a716-446655440000",
                entity_type=EntityType.JOB,
                spec=EmbeddingSpec(requested_types=[EmbeddingType.DENSE]),
                context=context,
            )

        message: EmbeddingRequested = mock_kafka_client.publish.call_args.kwargs["message"]
        assert message.command.operation_id == operation_id
        assert message.command.callback_topic == "test.sys.embedding-callback.v1"
        assert message.command.caller_context == b'{"test": true}'
        assert message.command.attributes == {"role": "retrieval"}

    @pytest.mark.anyio
    async def test_returns_valid_uuid(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """Returns a valid UUID string as operation_id."""
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            operation_id = await publisher.request_embedding(
                text="Software Engineer with Python",
                entity_id="550e8400-e29b-41d4-a716-446655440000",
                entity_type=EntityType.JOB,
                spec=EmbeddingSpec(requested_types=[EmbeddingType.DENSE]),
            )

        UUID(operation_id)

    @pytest.mark.anyio
    async def test_populates_request_fields(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """EmbeddingRequested message has correct domain fields."""
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            await publisher.request_embedding(
                text="Software Engineer with Python experience",
                entity_id="550e8400-e29b-41d4-a716-446655440000",
                entity_type=EntityType.JOB,
                spec=EmbeddingSpec(
                    requested_types=[EmbeddingType.MUVERA, EmbeddingType.SPARSE],
                    encoding_mode=EncodingMode.DOCUMENT,
                    publish_to_index=True,
                ),
            )

        message: EmbeddingRequested = mock_kafka_client.publish.call_args.kwargs["message"]
        assert message.entity_id == "550e8400-e29b-41d4-a716-446655440000"
        assert message.entity_type == EntityType.JOB
        assert message.text == "Software Engineer with Python experience"
        assert message.collection_version == "v1"
        assert list(message.requested_types) == [EmbeddingType.MUVERA, EmbeddingType.SPARSE]
        assert message.encoding_mode == EncodingMode.DOCUMENT
        assert message.publish_to_index is True

    @pytest.mark.anyio
    async def test_raises_on_no_kafka_client(
        self,
        publisher: EmbeddingPublisher,
    ) -> None:
        """Raises RuntimeError if Kafka client is not initialized."""
        with (
            patch(
                "nohiki_embedding_client.publisher.get_kafka_client",
                side_effect=RuntimeError("Kafka client not initialized"),
            ),
            pytest.raises(RuntimeError, match="Kafka client not initialized"),
        ):
            await publisher.request_embedding(
                text="test",
                entity_id="550e8400-e29b-41d4-a716-446655440000",
                entity_type=EntityType.JOB,
                spec=EmbeddingSpec(requested_types=[EmbeddingType.DENSE]),
            )


class TestRequestBatchEmbedding:
    """Tests for EmbeddingPublisher.request_batch_embedding."""

    @pytest.mark.anyio
    async def test_publishes_to_correct_topic(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """Publishes BatchEmbeddingRequested to ML_BATCH_EMBEDDING_REQUESTED topic."""
        items = [
            BatchEmbeddingItem(
                point_id="skill-1_label",
                entity_id="skill-1",
                text="Python programming",
            ),
        ]
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            await publisher.request_batch_embedding(
                items=items,
                entity_type=EntityType.SKILL,
                encoding_mode=EncodingMode.DOCUMENT,
            )

        call_kwargs = mock_kafka_client.publish.call_args.kwargs
        assert call_kwargs["topic"] == Topics.ML_BATCH_EMBEDDING_REQUESTED

    @pytest.mark.anyio
    async def test_builds_command_header(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """Builds CommandHeader with callback_topic and context."""
        items = [
            BatchEmbeddingItem(point_id="p1", entity_id="e1", text="test"),
        ]
        context = CommandContext(
            caller_context=b"saga-state",
            attributes={"batch": "true"},
        )
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            operation_id = await publisher.request_batch_embedding(
                items=items,
                entity_type=EntityType.SKILL,
                encoding_mode=EncodingMode.DOCUMENT,
                context=context,
            )

        message: BatchEmbeddingRequested = mock_kafka_client.publish.call_args.kwargs["message"]
        assert message.command.operation_id == operation_id
        assert message.command.callback_topic == "test.sys.embedding-callback.v1"
        assert message.command.caller_context == b"saga-state"
        assert message.command.attributes == {"batch": "true"}

    @pytest.mark.anyio
    async def test_raises_on_empty_items(
        self,
        publisher: EmbeddingPublisher,
    ) -> None:
        """Raises ValueError for empty batch items."""
        with pytest.raises(ValueError, match="must not be empty"):
            await publisher.request_batch_embedding(
                items=[],
                entity_type=EntityType.SKILL,
                encoding_mode=EncodingMode.DOCUMENT,
            )

    @pytest.mark.anyio
    async def test_raises_on_no_kafka_client(
        self,
        publisher: EmbeddingPublisher,
    ) -> None:
        """Raises RuntimeError if Kafka client is not initialized."""
        items = [
            BatchEmbeddingItem(point_id="p1", entity_id="e1", text="test"),
        ]
        with (
            patch(
                "nohiki_embedding_client.publisher.get_kafka_client",
                side_effect=RuntimeError("Kafka client not initialized"),
            ),
            pytest.raises(RuntimeError, match="Kafka client not initialized"),
        ):
            await publisher.request_batch_embedding(
                items=items,
                entity_type=EntityType.SKILL,
                encoding_mode=EncodingMode.DOCUMENT,
            )

    @pytest.mark.anyio
    async def test_returns_valid_uuid(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """Returns a valid UUID string as operation_id."""
        items = [
            BatchEmbeddingItem(point_id="p1", entity_id="e1", text="test"),
        ]
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            operation_id = await publisher.request_batch_embedding(
                items=items,
                entity_type=EntityType.SKILL,
                encoding_mode=EncodingMode.DOCUMENT,
            )

        UUID(operation_id)

    @pytest.mark.anyio
    async def test_key_is_operation_id(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """Batch messages use operation_id as the Kafka key."""
        items = [
            BatchEmbeddingItem(point_id="p1", entity_id="e1", text="test"),
        ]
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            operation_id = await publisher.request_batch_embedding(
                items=items,
                entity_type=EntityType.SKILL,
                encoding_mode=EncodingMode.DOCUMENT,
            )

        call_kwargs = mock_kafka_client.publish.call_args.kwargs
        assert call_kwargs["key"] == operation_id

    @pytest.mark.anyio
    async def test_populates_batch_domain_fields(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """BatchEmbeddingRequested message has correct entity_type, mode, and items."""
        items = [
            BatchEmbeddingItem(point_id="skill-1_label", entity_id="skill-1", text="Python"),
            BatchEmbeddingItem(point_id="skill-2_label", entity_id="skill-2", text="Go"),
        ]
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            await publisher.request_batch_embedding(
                items=items,
                entity_type=EntityType.SKILL,
                encoding_mode=EncodingMode.DOCUMENT,
            )

        message: BatchEmbeddingRequested = mock_kafka_client.publish.call_args.kwargs["message"]
        assert message.entity_type == EntityType.SKILL
        assert message.encoding_mode == EncodingMode.DOCUMENT
        assert message.collection_version == "v1"
        assert len(message.items) == 2

    @pytest.mark.anyio
    async def test_distinct_operation_ids_per_call(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """Each call generates a unique operation_id."""
        items = [BatchEmbeddingItem(point_id="p1", entity_id="e1", text="test")]
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            op1 = await publisher.request_batch_embedding(
                items=items, entity_type=EntityType.SKILL, encoding_mode=EncodingMode.DOCUMENT
            )
            op2 = await publisher.request_batch_embedding(
                items=items, entity_type=EntityType.SKILL, encoding_mode=EncodingMode.DOCUMENT
            )

        assert op1 != op2

    @pytest.mark.anyio
    async def test_default_context_is_empty(
        self,
        publisher: EmbeddingPublisher,
        mock_kafka_client: AsyncMock,
    ) -> None:
        """Default CommandContext produces empty caller_context and attributes."""
        items = [BatchEmbeddingItem(point_id="p1", entity_id="e1", text="test")]
        with patch(
            "nohiki_embedding_client.publisher.get_kafka_client",
            return_value=mock_kafka_client,
        ):
            await publisher.request_batch_embedding(
                items=items,
                entity_type=EntityType.SKILL,
                encoding_mode=EncodingMode.DOCUMENT,
            )

        message: BatchEmbeddingRequested = mock_kafka_client.publish.call_args.kwargs["message"]
        assert message.command.caller_context == b""
        assert message.command.attributes == {}

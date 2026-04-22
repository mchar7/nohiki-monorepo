"""Unit tests for ml_gateway_service.handlers module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ml_gateway_service.events.embedding import (
    _get_provider_for_embedding,
    _publish_embedding_failed,
    _route_to_provider,
    handle_embedding_requested,
)
from ml_gateway_service.events.metadata import create_event_metadata
from ml_gateway_service.exceptions import NoProviderAvailableError


class TestCreateEventMetadata:
    """Tests for create_event_metadata helper."""

    def test_creates_metadata_with_uuid(self) -> None:
        """Creates metadata with valid UUID event_id."""
        metadata = create_event_metadata()
        assert metadata.event_id is not None
        assert len(metadata.event_id) == 36

    def test_creates_metadata_with_timestamp(self) -> None:
        """Creates metadata with timestamp."""
        metadata = create_event_metadata()
        assert metadata.timestamp is not None

    def test_creates_metadata_with_source_service(self) -> None:
        """Creates metadata with source_service from settings."""
        metadata = create_event_metadata()
        assert metadata.source_service is not None

    def test_creates_metadata_with_correlation_id(self) -> None:
        """Creates metadata with provided correlation_id."""
        metadata = create_event_metadata("test-correlation-123")
        assert metadata.correlation_id == "test-correlation-123"

    def test_creates_metadata_without_correlation_id(self) -> None:
        """Creates metadata with None correlation_id when not provided."""
        metadata = create_event_metadata()
        assert metadata.correlation_id is None


class TestGetProviderForEmbedding:
    """Tests for _get_provider_for_embedding."""

    def test_returns_provider_when_available(self) -> None:
        """Returns provider when registry has available provider."""
        mock_provider = MagicMock()
        mock_provider.name = "kubernetes"

        with patch("ml_gateway_service.events.embedding.get_provider_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.get_provider_for_operation.return_value = mock_provider
            mock_get_registry.return_value = mock_registry

            message = MagicMock()
            message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
            message.entity_id = "test-entity"

            result = _get_provider_for_embedding(message)

            assert result is mock_provider

    def test_raises_when_no_provider_available(self) -> None:
        """Raises NoProviderAvailableError when no provider available."""
        with patch("ml_gateway_service.events.embedding.get_provider_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.get_provider_for_operation.return_value = None
            mock_get_registry.return_value = mock_registry

            message = MagicMock()
            message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
            message.entity_id = "test-entity"

            with pytest.raises(NoProviderAvailableError):
                _get_provider_for_embedding(message)


class TestRouteToProvider:
    """Tests for _route_to_provider."""

    @pytest.mark.asyncio
    async def test_publishes_internal_request(self) -> None:
        """Publishes InternalComputeRequest to provider's topic."""
        mock_provider = MagicMock()
        mock_provider.name = "kubernetes"
        mock_provider.get_target_topic.return_value = "ml.internal.k8s-compute.v1"

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "ml.callback.test.v1"
        message.entity_id = "550e8400-e29b-41d4-a716-446655440001"

        with patch("ml_gateway_service.events.embedding.kafka_client") as mock_kafka_client:
            mock_kafka_client.publish = AsyncMock()

            await _route_to_provider(message, mock_provider)

            mock_kafka_client.publish.assert_called_once()
            call_kwargs = mock_kafka_client.publish.call_args.kwargs
            assert call_kwargs["topic"] == "ml.internal.k8s-compute.v1"
            assert call_kwargs["key"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_raises_when_metadata_is_none(self) -> None:
        """Raises ValueError when message metadata is None."""
        mock_provider = MagicMock()
        mock_provider.name = "kubernetes"
        mock_provider.get_target_topic.return_value = "ml.internal.k8s-compute.v1"

        message = MagicMock()
        message.metadata = None

        with pytest.raises(ValueError, match="metadata is required"):
            await _route_to_provider(message, mock_provider)


class TestPublishEmbeddingFailed:
    """Tests for _publish_embedding_failed."""

    @pytest.mark.asyncio
    async def test_publishes_failed_event(self) -> None:
        """Publishes EmbeddingFailed event to callback topic."""
        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "ml.callback.test.v1"
        message.entity_id = "550e8400-e29b-41d4-a716-446655440001"
        message.entity_type = 1

        with patch("ml_gateway_service.events.embedding.kafka_client") as mock_kafka_client:
            mock_kafka_client.publish = AsyncMock()

            await _publish_embedding_failed(message, "Test error message")

            mock_kafka_client.publish.assert_called_once()
            call_kwargs = mock_kafka_client.publish.call_args.kwargs
            assert call_kwargs["topic"] == "ml.callback.test.v1"
            assert call_kwargs["key"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_raises_when_metadata_is_none(self) -> None:
        """Raises ValueError when message metadata is None."""
        message = MagicMock()
        message.metadata = None

        with pytest.raises(ValueError, match="metadata is required"):
            await _publish_embedding_failed(message, "Test error")


class TestHandleEmbeddingRequested:
    """Tests for handle_embedding_requested handler."""

    @pytest.mark.asyncio
    async def test_routes_to_provider_successfully(self) -> None:
        """Routes request to provider on success."""
        mock_provider = MagicMock()
        mock_provider.name = "kubernetes"
        mock_provider.get_target_topic.return_value = "ml.internal.k8s-compute.v1"

        message = MagicMock()
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.entity_id = "550e8400-e29b-41d4-a716-446655440001"
        context = MagicMock()

        with (
            patch(
                "ml_gateway_service.events.embedding._get_provider_for_embedding",
                return_value=mock_provider,
            ),
            patch(
                "ml_gateway_service.events.embedding._route_to_provider",
                new_callable=AsyncMock,
            ) as mock_route,
        ):
            await handle_embedding_requested(message, context)

            mock_route.assert_called_once_with(message, mock_provider)

    @pytest.mark.asyncio
    async def test_publishes_failed_and_reraises_on_no_provider(self) -> None:
        """Publishes failed event and re-raises when no provider available."""
        message = MagicMock()
        message.request_id = "550e8400-e29b-41d4-a716-446655440000"
        message.entity_id = "550e8400-e29b-41d4-a716-446655440001"
        context = MagicMock()

        with (
            patch(
                "ml_gateway_service.events.embedding._get_provider_for_embedding",
                side_effect=NoProviderAvailableError("embedding"),
            ),
            patch(
                "ml_gateway_service.events.embedding._publish_embedding_failed",
                new_callable=AsyncMock,
            ),
            pytest.raises(NoProviderAvailableError),
        ):
            await handle_embedding_requested(message, context)

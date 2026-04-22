"""Tests for ml_gateway_service.events.rerank module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ml_gateway_service.exceptions import NoProviderAvailableError


class TestHandleRerankRequested:
    """Tests for handle_rerank_requested handler."""

    @pytest.mark.asyncio
    async def test_routes_rerank_request_to_provider(self) -> None:
        """Test successful routing of rerank request to provider."""
        from ml_gateway_service.events.rerank import handle_rerank_requested

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "ml.callback.test.v1"
        message.documents = ["doc1", "doc2"]

        context = MagicMock()

        mock_provider = MagicMock()
        mock_provider.name = "modal"
        mock_provider.get_target_topic.return_value = "ml.internal.modal-compute.v1"

        with (
            patch(
                "ml_gateway_service.events.rerank._get_provider_or_fail",
                return_value=mock_provider,
            ),
            patch(
                "ml_gateway_service.events.rerank._route_to_provider",
                new_callable=AsyncMock,
            ) as mock_route,
        ):
            await handle_rerank_requested(message, context)

            mock_route.assert_called_once_with(message, context, mock_provider)


class TestGetProviderOrFail:
    """Tests for _get_provider_or_fail function."""

    def test_returns_provider_when_available(self) -> None:
        """Test returns provider when registry has available provider."""
        from ml_gateway_service.events.rerank import _get_provider_or_fail

        mock_provider = MagicMock()
        mock_provider.name = "modal"

        with patch("ml_gateway_service.events.rerank.get_provider_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.get_provider_for_operation.return_value = mock_provider
            mock_get_registry.return_value = mock_registry

            message = MagicMock()
            message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"

            result = _get_provider_or_fail(message)

            assert result is mock_provider
            mock_registry.get_provider_for_operation.assert_called_once()

    def test_raises_no_provider_available_error(self) -> None:
        """Test raises NoProviderAvailableError when no provider available."""
        from ml_gateway_service.events.rerank import _get_provider_or_fail

        with patch("ml_gateway_service.events.rerank.get_provider_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.get_provider_for_operation.return_value = None
            mock_get_registry.return_value = mock_registry

            message = MagicMock()
            message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"

            with pytest.raises(NoProviderAvailableError):
                _get_provider_or_fail(message)


class TestRouteToProvider:
    """Tests for _route_to_provider function."""

    @pytest.mark.asyncio
    async def test_publishes_internal_request(self) -> None:
        """Test publishes InternalComputeRequest to provider's topic."""
        from ml_gateway_service.events.rerank import _route_to_provider

        mock_provider = MagicMock()
        mock_provider.name = "modal"
        mock_provider.get_target_topic.return_value = "ml.internal.modal-compute.v1"

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "ml.callback.test.v1"

        context = MagicMock()

        with patch("ml_gateway_service.events.rerank.kafka_client") as mock_kafka_client:
            mock_kafka_client.publish = AsyncMock()

            await _route_to_provider(message, context, mock_provider)

            mock_kafka_client.publish.assert_called_once()
            call_kwargs = mock_kafka_client.publish.call_args.kwargs
            assert call_kwargs["topic"] == "ml.internal.modal-compute.v1"


class TestCreateEventMetadata:
    """Tests for create_event_metadata helper."""

    def test_creates_metadata_with_uuid(self) -> None:
        """Test creates metadata with valid UUID event_id."""
        from ml_gateway_service.events.metadata import create_event_metadata

        metadata = create_event_metadata()

        assert metadata.event_id is not None
        assert len(metadata.event_id) == 36

    def test_creates_metadata_with_correlation_id(self) -> None:
        """Test creates metadata with provided correlation_id."""
        from ml_gateway_service.events.metadata import create_event_metadata

        metadata = create_event_metadata("test-correlation-123")

        assert metadata.correlation_id == "test-correlation-123"

    def test_creates_metadata_without_correlation_id(self) -> None:
        """Test creates metadata with None correlation_id when not provided."""
        from ml_gateway_service.events.metadata import create_event_metadata

        metadata = create_event_metadata()

        assert metadata.correlation_id is None


class TestPublishRoutingFailed:
    """Tests for _publish_routing_failed function."""

    @pytest.mark.asyncio
    async def test_publishes_failed_event(self) -> None:
        """Test publishes RerankFailed event to callback topic."""
        from ml_gateway_service.events.rerank import _publish_routing_failed

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "ml.callback.test.v1"

        with patch("ml_gateway_service.events.rerank.kafka_client") as mock_kafka_client:
            mock_kafka_client.publish = AsyncMock()

            await _publish_routing_failed(message, "Routing failed")

            mock_kafka_client.publish.assert_called_once()
            call_kwargs = mock_kafka_client.publish.call_args.kwargs
            assert call_kwargs["topic"] == "ml.callback.test.v1"
            assert call_kwargs["key"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_publishes_failed_event_without_metadata(self) -> None:
        """Test publishes RerankFailed when metadata is None."""
        from ml_gateway_service.events.rerank import _publish_routing_failed

        message = MagicMock()
        message.metadata = None
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "ml.callback.test.v1"

        with patch("ml_gateway_service.events.rerank.kafka_client") as mock_kafka_client:
            mock_kafka_client.publish = AsyncMock()

            await _publish_routing_failed(message, "Routing failed")

            mock_kafka_client.publish.assert_called_once()

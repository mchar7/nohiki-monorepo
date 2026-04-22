"""Tests for ml_gateway_service.events.batch_embedding module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ml_gateway_service.exceptions import NoProviderAvailableError
from nohiki.ml.v1 import EncodingMode


class TestHandleBatchEmbeddingRequested:
    """Tests for handle_batch_embedding_requested handler."""

    @pytest.mark.asyncio
    async def test_routes_request_to_provider_on_success(self) -> None:
        """Test successful routing of batch embedding request to provider."""
        from ml_gateway_service.events.batch_embedding import handle_batch_embedding_requested

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "skill.sys.batch-callback.v1"
        message.items = [MagicMock(), MagicMock()]

        context = MagicMock()

        mock_provider = MagicMock()
        mock_provider.name = "kubernetes"
        mock_provider.get_target_topic.return_value = "ml.internal.k8s-compute.v1"

        with (
            patch(
                "ml_gateway_service.events.batch_embedding._get_provider_for_batch_embedding",
                return_value=mock_provider,
            ),
            patch(
                "ml_gateway_service.events.batch_embedding._route_to_provider",
                new_callable=AsyncMock,
            ) as mock_route,
        ):
            await handle_batch_embedding_requested(message, context)

            mock_route.assert_called_once_with(message, mock_provider)

    @pytest.mark.asyncio
    async def test_publishes_one_terminal_failure_and_returns_when_no_provider(self) -> None:
        """Test a terminal callback is published without triggering Kafka redelivery."""
        from ml_gateway_service.events.batch_embedding import handle_batch_embedding_requested

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "skill.sys.batch-callback.v1"
        message.items = [MagicMock()]

        context = MagicMock()

        with (
            patch(
                "ml_gateway_service.events.batch_embedding._get_provider_for_batch_embedding",
                side_effect=NoProviderAvailableError("batch_embedding"),
            ),
            patch(
                "ml_gateway_service.events.batch_embedding._publish_batch_failed",
                new_callable=AsyncMock,
            ) as mock_publish_failed,
        ):
            await handle_batch_embedding_requested(message, context)

            mock_publish_failed.assert_awaited_once_with(
                message,
                "No ML provider available for batch embedding operation",
                error_code="NO_PROVIDER",
            )

    @pytest.mark.asyncio
    async def test_publishes_one_terminal_failure_and_returns_for_invalid_batch(self) -> None:
        """An invalid batch produces exactly one terminal callback without routing."""
        from ml_gateway_service.events.batch_embedding import handle_batch_embedding_requested

        message = MagicMock()
        message.items = []
        provider = MagicMock()
        provider.capabilities.max_batch_size = 32

        with (
            patch(
                "ml_gateway_service.events.batch_embedding._get_provider_for_batch_embedding",
                return_value=provider,
            ),
            patch(
                "ml_gateway_service.events.batch_embedding._publish_batch_failed",
                new_callable=AsyncMock,
            ) as mock_publish_failed,
            patch(
                "ml_gateway_service.events.batch_embedding._route_to_provider",
                new_callable=AsyncMock,
            ) as mock_route,
        ):
            await handle_batch_embedding_requested(message, MagicMock())

        mock_publish_failed.assert_awaited_once_with(
            message,
            "Batch size 0 must be between 1 and 32",
            error_code="INVALID_BATCH_SIZE",
        )
        mock_route.assert_not_awaited()


class TestGetProviderForBatchEmbedding:
    """Tests for _get_provider_for_batch_embedding."""

    def test_returns_provider_when_available(self) -> None:
        """Test returns provider when registry has a batch-embedding-capable provider."""
        from ml_gateway_service.events.batch_embedding import _get_provider_for_batch_embedding

        mock_provider = MagicMock()
        mock_provider.name = "kubernetes"

        with patch("ml_gateway_service.events.batch_embedding.get_provider_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.get_provider_for_operation.return_value = mock_provider
            mock_get_registry.return_value = mock_registry

            message = MagicMock()
            message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
            message.entity_type.name = "SKILL"
            message.items = [MagicMock()]

            result = _get_provider_for_batch_embedding(message)

            assert result is mock_provider

    def test_raises_no_provider_available_error_when_none(self) -> None:
        """Test raises NoProviderAvailableError when no provider available."""
        from ml_gateway_service.events.batch_embedding import _get_provider_for_batch_embedding

        with patch("ml_gateway_service.events.batch_embedding.get_provider_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.get_provider_for_operation.return_value = None
            mock_get_registry.return_value = mock_registry

            message = MagicMock()
            message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
            message.entity_type.name = "SKILL"
            message.items = [MagicMock()]

            with pytest.raises(NoProviderAvailableError):
                _get_provider_for_batch_embedding(message)


class TestRouteToProvider:
    """Tests for _route_to_provider."""

    @pytest.mark.asyncio
    async def test_publishes_internal_compute_request_to_provider_topic(self) -> None:
        """Test publishes InternalComputeRequest wrapped request to provider's topic."""
        from ml_gateway_service.events.batch_embedding import _route_to_provider
        from nohiki.ml.v1 import InternalComputeRequest

        mock_provider = MagicMock()
        mock_provider.name = "kubernetes"
        mock_provider.get_target_topic.return_value = "ml.internal.k8s-compute.v1"

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "skill.sys.batch-callback.v1"
        message.items = [MagicMock(), MagicMock(), MagicMock()]

        with patch("ml_gateway_service.events.batch_embedding.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await _route_to_provider(message, mock_provider)

            mock_kafka.publish.assert_called_once()
            call_kwargs = mock_kafka.publish.call_args.kwargs
            assert call_kwargs["topic"] == "ml.internal.k8s-compute.v1"
            assert call_kwargs["key"] == "550e8400-e29b-41d4-a716-446655440000"
            assert isinstance(call_kwargs["message"], InternalComputeRequest)

    @pytest.mark.asyncio
    async def test_raises_value_error_when_metadata_is_none(self) -> None:
        """Test ValueError raised when message.metadata is None."""
        from ml_gateway_service.events.batch_embedding import _route_to_provider

        mock_provider = MagicMock()
        mock_provider.get_target_topic.return_value = "ml.internal.k8s-compute.v1"

        message = MagicMock()
        message.metadata = None
        message.batch_id = "550e8400-e29b-41d4-a716-446655440000"

        with pytest.raises(ValueError, match="metadata is required"):
            await _route_to_provider(message, mock_provider)

    @pytest.mark.asyncio
    async def test_internal_request_carries_correct_correlation_id(self) -> None:
        """Test InternalComputeRequest.original_correlation_id equals batch_id."""
        from ml_gateway_service.events.batch_embedding import _route_to_provider
        from nohiki.ml.v1 import InternalComputeRequest

        mock_provider = MagicMock()
        mock_provider.name = "kubernetes"
        mock_provider.get_target_topic.return_value = "ml.internal.k8s-compute.v1"

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "skill.sys.batch-callback.v1"
        message.items = []

        with patch("ml_gateway_service.events.batch_embedding.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await _route_to_provider(message, mock_provider)

            internal: InternalComputeRequest = mock_kafka.publish.call_args.kwargs["message"]
            assert internal.batch_embedding_request is message
            assert internal.selected_provider == "kubernetes"


class TestPublishBatchFailed:
    """Tests for _publish_batch_failed."""

    @pytest.mark.asyncio
    async def test_publishes_batch_embedding_failed_to_callback_topic(self) -> None:
        """Test publishes BatchEmbeddingCallback error to message.command.callback_topic."""
        from ml_gateway_service.events.batch_embedding import _publish_batch_failed
        from nohiki.ml.v1 import BatchEmbeddingCallback

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "skill.sys.batch-callback.v1"
        message.entity_type = MagicMock()
        message.collection_version = "skills-v7"
        message.encoding_mode = EncodingMode.QUERY

        with patch("ml_gateway_service.events.batch_embedding.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await _publish_batch_failed(message, "No provider found", error_code="NO_PROVIDER")

            mock_kafka.publish.assert_called_once()
            call_kwargs = mock_kafka.publish.call_args.kwargs
            assert call_kwargs["topic"] == "skill.sys.batch-callback.v1"
            assert call_kwargs["key"] == "550e8400-e29b-41d4-a716-446655440000"
            assert isinstance(call_kwargs["message"], BatchEmbeddingCallback)
            failed = call_kwargs["message"]
            assert failed.collection_version == "skills-v7"
            assert failed.encoding_mode == EncodingMode.QUERY

    @pytest.mark.asyncio
    async def test_raises_value_error_when_metadata_is_none(self) -> None:
        """Test ValueError raised when message.metadata is None."""
        from ml_gateway_service.events.batch_embedding import _publish_batch_failed

        message = MagicMock()
        message.metadata = None
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"

        with pytest.raises(ValueError, match="metadata is required"):
            await _publish_batch_failed(message, "No provider", error_code="NO_PROVIDER")

    @pytest.mark.asyncio
    async def test_failed_event_carries_correct_error_fields(self) -> None:
        """Test published BatchEmbeddingCallback.error carries the correct error_code and message."""
        from ml_gateway_service.events.batch_embedding import _publish_batch_failed
        from nohiki.ml.v1 import BatchEmbeddingCallback

        mock_metadata = MagicMock()
        mock_metadata.correlation_id = "test-correlation"

        message = MagicMock()
        message.metadata = mock_metadata
        message.command.operation_id = "550e8400-e29b-41d4-a716-446655440000"
        message.command.callback_topic = "skill.sys.batch-callback.v1"
        message.entity_type = MagicMock()

        with patch("ml_gateway_service.events.batch_embedding.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await _publish_batch_failed(
                message,
                "No ML provider available for batch embedding operation",
                error_code="NO_PROVIDER",
            )

            failed: BatchEmbeddingCallback = mock_kafka.publish.call_args.kwargs["message"]
            assert failed.error is not None
            assert failed.error.error_code == "NO_PROVIDER"
            assert "No ML provider" in failed.error.error_message
            assert failed.error.retryable is False

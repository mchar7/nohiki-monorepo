"""Tests for doc_process_service.events.publishers module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from doc_process_service.events.publishers import (
    publish_processing_completed,
    publish_processing_failed,
)
from doc_process_service.events.types import ProcessingParams
from nohiki.common.v1 import CommandHeader
from nohiki.doc.process.v1 import ProcessedDocumentSnapshot, ProcessingCallback, ProcessingLevel

_DEFAULT_CMD = CommandHeader(
    operation_id="req-123",
    callback_topic="my-callback-topic",
    caller_context=b"ctx",
    attributes={"user_id": "user-123"},
)


@pytest.fixture
def processing_params() -> ProcessingParams:
    """Create test ProcessingParams using CommandHeader."""
    return ProcessingParams(
        command=_DEFAULT_CMD,
        storage_key="s3://bucket/key",
        content_id="content-456",
        processing_level=ProcessingLevel.TABLES,
        correlation_id="corr-789",
    )


@pytest.fixture
def processed_snapshot() -> ProcessedDocumentSnapshot:
    """Create test ProcessedDocumentSnapshot."""
    return ProcessedDocumentSnapshot(
        content_id="content-456",
        content_hash="abc123hash",
        level=ProcessingLevel.TABLES,
        markdown="# Test Document\n\nSome content.",
        html="<h1>Test Document</h1>",
        table_count=2,
        image_count=0,
    )


class TestPublishProcessingCompleted:
    """Tests for publish_processing_completed function."""

    @pytest.mark.asyncio
    @patch("doc_process_service.events.publishers.kafka_client")
    @patch("doc_process_service.events.publishers.get_settings")
    async def test_publishes_to_callback_topic(
        self,
        mock_get_settings: MagicMock,
        mock_kafka_client: MagicMock,
        processing_params: ProcessingParams,
        processed_snapshot: ProcessedDocumentSnapshot,
    ) -> None:
        """Publishes ProcessingCallback to command.callback_topic."""
        mock_settings = MagicMock()
        mock_settings.service_name = "doc-process-service"
        mock_get_settings.return_value = mock_settings
        mock_kafka_client.publish = AsyncMock()

        await publish_processing_completed(processing_params, processed_snapshot)

        mock_kafka_client.publish.assert_called_once()
        call_args = mock_kafka_client.publish.call_args
        assert call_args[0][0] == "my-callback-topic"
        assert call_args[1]["key"] == "req-123"
        assert isinstance(call_args[0][1], ProcessingCallback)

    @pytest.mark.asyncio
    @patch("doc_process_service.events.publishers.kafka_client")
    @patch("doc_process_service.events.publishers.get_settings")
    async def test_success_payload_contains_snapshot(
        self,
        mock_get_settings: MagicMock,
        mock_kafka_client: MagicMock,
        processing_params: ProcessingParams,
        processed_snapshot: ProcessedDocumentSnapshot,
    ) -> None:
        """Success field contains the snapshot."""
        mock_settings = MagicMock()
        mock_settings.service_name = "doc-process-service"
        mock_get_settings.return_value = mock_settings
        mock_kafka_client.publish = AsyncMock()

        await publish_processing_completed(processing_params, processed_snapshot)

        event: ProcessingCallback = mock_kafka_client.publish.call_args[0][1]
        assert event.success is not None
        assert event.success.snapshot is processed_snapshot
        assert event.error is None

    @pytest.mark.asyncio
    @patch("doc_process_service.events.publishers.kafka_client")
    @patch("doc_process_service.events.publishers.get_settings")
    async def test_callback_header_echoes_command_fields(
        self,
        mock_get_settings: MagicMock,
        mock_kafka_client: MagicMock,
        processing_params: ProcessingParams,
        processed_snapshot: ProcessedDocumentSnapshot,
    ) -> None:
        """Callback header echoes operation_id, caller_context, and attributes from command."""
        mock_settings = MagicMock()
        mock_settings.service_name = "doc-process-service"
        mock_get_settings.return_value = mock_settings
        mock_kafka_client.publish = AsyncMock()

        await publish_processing_completed(processing_params, processed_snapshot)

        event: ProcessingCallback = mock_kafka_client.publish.call_args[0][1]
        assert event.callback.operation_id == "req-123"
        assert event.callback.caller_context == b"ctx"
        assert event.callback.attributes == {"user_id": "user-123"}


class TestPublishProcessingFailed:
    """Tests for publish_processing_failed function."""

    @pytest.mark.asyncio
    @patch("doc_process_service.events.publishers.kafka_client")
    @patch("doc_process_service.events.publishers.get_settings")
    async def test_publishes_to_callback_topic(
        self,
        mock_get_settings: MagicMock,
        mock_kafka_client: MagicMock,
        processing_params: ProcessingParams,
    ) -> None:
        """Publishes ProcessingCallback error to command.callback_topic."""
        mock_settings = MagicMock()
        mock_settings.service_name = "doc-process-service"
        mock_get_settings.return_value = mock_settings
        mock_kafka_client.publish = AsyncMock()

        await publish_processing_failed(
            processing_params,
            error_code="TIMEOUT",
            error_message="Processing timed out",
            is_retryable=True,
        )

        mock_kafka_client.publish.assert_called_once()
        call_args = mock_kafka_client.publish.call_args
        assert call_args[0][0] == "my-callback-topic"
        assert call_args[1]["key"] == "req-123"
        assert isinstance(call_args[0][1], ProcessingCallback)

    @pytest.mark.asyncio
    @patch("doc_process_service.events.publishers.kafka_client")
    @patch("doc_process_service.events.publishers.get_settings")
    async def test_error_payload_contains_error_info(
        self,
        mock_get_settings: MagicMock,
        mock_kafka_client: MagicMock,
        processing_params: ProcessingParams,
    ) -> None:
        """Error field contains ErrorInfo with correct fields."""
        mock_settings = MagicMock()
        mock_settings.service_name = "doc-process-service"
        mock_get_settings.return_value = mock_settings
        mock_kafka_client.publish = AsyncMock()

        await publish_processing_failed(
            processing_params,
            error_code="VALIDATION_ERROR",
            error_message="Invalid document format",
            is_retryable=False,
        )

        event: ProcessingCallback = mock_kafka_client.publish.call_args[0][1]
        assert event.error is not None
        assert event.error.error_code == "VALIDATION_ERROR"
        assert event.error.error_message == "Invalid document format"
        assert event.error.retryable is False
        assert event.success is None

    @pytest.mark.asyncio
    @patch("doc_process_service.events.publishers.kafka_client")
    @patch("doc_process_service.events.publishers.get_settings")
    async def test_callback_header_echoes_command_fields(
        self,
        mock_get_settings: MagicMock,
        mock_kafka_client: MagicMock,
        processing_params: ProcessingParams,
    ) -> None:
        """Callback header echoes caller_context and attributes from command."""
        mock_settings = MagicMock()
        mock_settings.service_name = "doc-process-service"
        mock_get_settings.return_value = mock_settings
        mock_kafka_client.publish = AsyncMock()

        await publish_processing_failed(
            processing_params,
            error_code="ERROR",
            error_message="Failed",
            is_retryable=True,
        )

        event: ProcessingCallback = mock_kafka_client.publish.call_args[0][1]
        assert event.callback.operation_id == "req-123"
        assert event.callback.caller_context == b"ctx"
        assert event.callback.attributes == {"user_id": "user-123"}

    @pytest.mark.asyncio
    @patch("doc_process_service.events.publishers.kafka_client")
    @patch("doc_process_service.events.publishers.get_settings")
    async def test_handles_empty_attributes(
        self,
        mock_get_settings: MagicMock,
        mock_kafka_client: MagicMock,
    ) -> None:
        """Empty attributes dict in CommandHeader produces empty dict in callback."""
        mock_settings = MagicMock()
        mock_settings.service_name = "doc-process-service"
        mock_get_settings.return_value = mock_settings
        mock_kafka_client.publish = AsyncMock()

        params_no_attrs = ProcessingParams(
            command=CommandHeader(
                operation_id="req-123",
                callback_topic="my-callback-topic",
                attributes={},
            ),
            storage_key="s3://bucket/key",
            content_id="content-456",
            processing_level=ProcessingLevel.BASIC,
            correlation_id="corr-789",
        )

        await publish_processing_failed(
            params_no_attrs,
            error_code="ERROR",
            error_message="Failed",
            is_retryable=False,
        )

        event: ProcessingCallback = mock_kafka_client.publish.call_args[0][1]
        assert event.callback.attributes == {}

"""Tests for doc_process_service.events.handlers module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from doc_process_service.events.handlers import (
    _build_processing_options,
    _build_processing_params,
    _process_document,
    handle_processing_requested,
)
from doc_process_service.events.types import ProcessingParams
from doc_process_service.models.domain import ProcessingResult
from nohiki.common.v1 import CommandHeader, EventMetadata
from nohiki.doc.process.v1 import ProcessedDocumentSnapshot, ProcessingLevel, ProcessingRequested
from nohiki_kafka_client import MessageContext
from nohiki_s3_client import S3ObjectNotFoundError


@pytest.fixture
def mock_message_context() -> MagicMock:
    """Create mock MessageContext."""
    return MagicMock(spec=MessageContext)


@pytest.fixture
def processing_requested_message() -> ProcessingRequested:
    """Create test ProcessingRequested message."""
    return ProcessingRequested(
        metadata=EventMetadata(
            event_id="evt-123",
            correlation_id="corr-456",
            source_service="test-service",
        ),
        command=CommandHeader(
            operation_id="req-789",
            callback_topic="my-callback-topic",
            caller_context=b"ctx",
            attributes={"user_id": "user-123"},
        ),
        user_id="11111111-1111-4111-8111-111111111111",
        storage_key=(
            "user-uploads/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/document.pdf"
        ),
        content_id="22222222-2222-4222-8222-222222222222",
        processing_level=ProcessingLevel.TABLES,
    )


@pytest.fixture
def processing_params() -> ProcessingParams:
    """Create test ProcessingParams."""
    return ProcessingParams(
        command=CommandHeader(
            operation_id="req-789",
            callback_topic="my-callback-topic",
            caller_context=b"ctx",
            attributes={"user_id": "user-123"},
        ),
        storage_key="s3://bucket/document.pdf",
        content_id="content-abc",
        processing_level=ProcessingLevel.TABLES,
        correlation_id="corr-456",
    )


class TestBuildProcessingParams:
    """Tests for _build_processing_params function."""

    def test_extracts_all_fields(
        self,
        processing_requested_message: ProcessingRequested,
    ) -> None:
        """Extracts all fields from message, preserving CommandHeader as-is."""
        params = _build_processing_params(processing_requested_message)

        assert params.command.operation_id == "req-789"
        assert params.storage_key == (
            "user-uploads/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/document.pdf"
        )
        assert params.content_id == "22222222-2222-4222-8222-222222222222"
        assert params.processing_level == ProcessingLevel.TABLES
        assert params.command.callback_topic == "my-callback-topic"
        assert params.correlation_id == "corr-456"
        assert params.command.attributes == {"user_id": "user-123"}
        assert params.command.caller_context == b"ctx"

    def test_uses_operation_id_as_correlation_id_fallback(self) -> None:
        """Test uses operation_id when correlation_id is empty."""
        message = ProcessingRequested(
            metadata=EventMetadata(
                event_id="evt-123",
                correlation_id="",
                source_service="test-service",
            ),
            command=CommandHeader(
                operation_id="req-789",
                callback_topic="my-callback",
            ),
            user_id="11111111-1111-4111-8111-111111111111",
            storage_key=(
                "user-uploads/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/doc.pdf"
            ),
            content_id="22222222-2222-4222-8222-222222222222",
        )

        params = _build_processing_params(message)

        assert params.correlation_id == "req-789"

    def test_defaults_to_basic_level(self) -> None:
        """Test defaults to BASIC when level is UNSPECIFIED."""
        message = ProcessingRequested(
            metadata=EventMetadata(
                event_id="evt-123",
                correlation_id="corr-456",
                source_service="test-service",
            ),
            command=CommandHeader(
                operation_id="req-789",
                callback_topic="my-callback",
            ),
            user_id="11111111-1111-4111-8111-111111111111",
            storage_key=(
                "user-uploads/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/doc.pdf"
            ),
            content_id="22222222-2222-4222-8222-222222222222",
            processing_level=ProcessingLevel.UNSPECIFIED,
        )

        params = _build_processing_params(message)

        assert params.processing_level == ProcessingLevel.BASIC


class TestBuildProcessingOptions:
    """Tests for _build_processing_options function."""

    def test_basic_level_options(self) -> None:
        """Test BASIC level options."""
        options = _build_processing_options(ProcessingLevel.BASIC)

        assert options.enable_ocr is False
        assert options.extract_tables is False
        assert options.extract_images is False
        assert options.enable_vlm_descriptions is False

    def test_tables_level_options(self) -> None:
        """Test TABLES level options."""
        options = _build_processing_options(ProcessingLevel.TABLES)

        assert options.enable_ocr is False
        assert options.extract_tables is True
        assert options.extract_images is False
        assert options.enable_vlm_descriptions is False

    def test_ocr_level_options(self) -> None:
        """Test OCR level options."""
        options = _build_processing_options(ProcessingLevel.OCR)

        assert options.enable_ocr is True
        assert options.extract_tables is True
        assert options.extract_images is False
        assert options.enable_vlm_descriptions is False

    def test_images_level_options(self) -> None:
        """Test IMAGES level options."""
        options = _build_processing_options(ProcessingLevel.IMAGES)

        assert options.enable_ocr is True
        assert options.extract_tables is True
        assert options.extract_images is True
        assert options.enable_vlm_descriptions is False

    def test_full_level_options(self) -> None:
        """Test FULL level options."""
        options = _build_processing_options(ProcessingLevel.FULL)

        assert options.enable_ocr is True
        assert options.extract_tables is True
        assert options.extract_images is True
        assert options.enable_vlm_descriptions is True


class TestHandleProcessingRequested:
    """Tests for handle_processing_requested function."""

    @pytest.mark.asyncio
    @patch("doc_process_service.events.handlers._process_document")
    async def test_accepts_matching_tenant_content_storage_key(
        self,
        mock_process_document: AsyncMock,
        processing_requested_message: ProcessingRequested,
        mock_message_context: MagicMock,
    ) -> None:
        """Accept a canonical tenant key bound to the requested content."""
        mock_process_document.return_value = None

        await handle_processing_requested(processing_requested_message, mock_message_context)

        mock_process_document.assert_called_once()
        call_args = mock_process_document.call_args[0][0]
        assert call_args.command.operation_id == "req-789"
        assert call_args.storage_key == processing_requested_message.storage_key
        assert call_args.content_id == processing_requested_message.content_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "storage_key",
        [
            ("user-uploads/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/22222222-2222-4222-8222-222222222222/document.pdf"),
            ("user-uploads/11111111-1111-4111-8111-111111111111/33333333-3333-4333-8333-333333333333/document.pdf"),
            "not-a-user-upload-key",
        ],
        ids=["different-user", "different-content", "malformed"],
    )
    @patch("doc_process_service.events.handlers.publish_processing_failed")
    @patch("doc_process_service.events.handlers.get_s3_client")
    @patch("doc_process_service.events.handlers._process_document")
    async def test_publishes_terminal_failure_for_invalid_storage_key(
        self,
        mock_process_document: AsyncMock,
        mock_get_s3_client: MagicMock,
        mock_publish_failed: AsyncMock,
        storage_key: str,
        processing_requested_message: ProcessingRequested,
        mock_message_context: MagicMock,
    ) -> None:
        """Invalid storage identity publishes one correlated terminal failure without I/O."""
        processing_requested_message.storage_key = storage_key

        await handle_processing_requested(processing_requested_message, mock_message_context)

        mock_publish_failed.assert_awaited_once()
        params = mock_publish_failed.call_args.args[0]
        assert params.correlation_id == "corr-456"
        assert params.command.operation_id == "req-789"
        call_kwargs = mock_publish_failed.call_args.kwargs
        assert call_kwargs["error_code"] == "INVALID_STORAGE_KEY"
        assert call_kwargs["is_retryable"] is False
        mock_process_document.assert_not_awaited()
        mock_get_s3_client.assert_not_called()


class TestProcessDocument:
    """Tests for _process_document function."""

    @pytest.mark.asyncio
    @patch("doc_process_service.events.handlers.publish_processing_completed")
    @patch("doc_process_service.events.handlers._get_processing_service")
    @patch("doc_process_service.events.handlers.get_s3_client")
    async def test_successful_processing(
        self,
        mock_get_s3_client: MagicMock,
        mock_get_service: MagicMock,
        mock_publish_completed: AsyncMock,
        processing_params: ProcessingParams,
    ) -> None:
        """Test successful document processing flow."""
        mock_s3 = MagicMock()
        mock_s3.get_object = AsyncMock(return_value=b"document content")
        mock_get_s3_client.return_value = mock_s3

        mock_service = MagicMock()
        processed_snapshot = ProcessedDocumentSnapshot(
            content_id="content-abc",
            content_hash="hash123",
            level=ProcessingLevel.TABLES,
            markdown="# Document",
        )
        mock_service.process = AsyncMock(return_value=ProcessingResult(content=processed_snapshot))
        mock_get_service.return_value = mock_service

        await _process_document(processing_params)

        mock_s3.get_object.assert_called_once_with("s3://bucket/document.pdf", max_bytes=50 * 1024 * 1024)
        mock_service.process.assert_called_once()
        mock_publish_completed.assert_called_once()

    @pytest.mark.asyncio
    @patch("doc_process_service.events.handlers.publish_processing_failed")
    @patch("doc_process_service.events.handlers._get_processing_service")
    @patch("doc_process_service.events.handlers.get_s3_client")
    async def test_publishes_failure_on_processing_error(
        self,
        mock_get_s3_client: MagicMock,
        mock_get_service: MagicMock,
        mock_publish_failed: AsyncMock,
        processing_params: ProcessingParams,
    ) -> None:
        """Test publishes failure event when processing fails."""
        mock_s3 = MagicMock()
        mock_s3.get_object = AsyncMock(return_value=b"document content")
        mock_get_s3_client.return_value = mock_s3

        mock_service = MagicMock()
        mock_service.process = AsyncMock(return_value=ProcessingResult(error="Processing failed"))
        mock_get_service.return_value = mock_service

        await _process_document(processing_params)

        mock_publish_failed.assert_called_once()
        call_kwargs = mock_publish_failed.call_args[1]
        assert call_kwargs["error_code"] == "PROCESSING_FAILED"

    @pytest.mark.asyncio
    @patch("doc_process_service.events.handlers.publish_processing_failed")
    @patch("doc_process_service.events.handlers.get_s3_client")
    async def test_publishes_terminal_failure_on_missing_s3_object(
        self,
        mock_get_s3_client: MagicMock,
        mock_publish_failed: AsyncMock,
        processing_params: ProcessingParams,
    ) -> None:
        """A missing object is terminal and must not trigger Kafka redelivery."""
        mock_s3 = MagicMock()
        mock_s3.get_object = AsyncMock(side_effect=S3ObjectNotFoundError("s3://bucket/document.pdf"))
        mock_get_s3_client.return_value = mock_s3

        await _process_document(processing_params)

        mock_publish_failed.assert_awaited_once()
        call_kwargs = mock_publish_failed.call_args.kwargs
        assert call_kwargs["error_code"] == "DOCUMENT_NOT_FOUND"
        assert call_kwargs["is_retryable"] is False

    @pytest.mark.asyncio
    @patch("doc_process_service.events.handlers.publish_processing_failed")
    @patch("doc_process_service.events.handlers._get_processing_service")
    @patch("doc_process_service.events.handlers.get_s3_client")
    async def test_raises_on_unexpected_error(
        self,
        mock_get_s3_client: MagicMock,
        mock_get_service: MagicMock,
        mock_publish_failed: AsyncMock,
        processing_params: ProcessingParams,
    ) -> None:
        """Test raises and publishes failure on unexpected error."""
        mock_s3 = MagicMock()
        mock_s3.get_object = AsyncMock(return_value=b"document content")
        mock_get_s3_client.return_value = mock_s3

        mock_service = MagicMock()
        mock_service.process = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        mock_get_service.return_value = mock_service

        with pytest.raises(RuntimeError, match="Unexpected error"):
            await _process_document(processing_params)

        mock_publish_failed.assert_called_once()
        call_kwargs = mock_publish_failed.call_args[1]
        assert call_kwargs["error_code"] == "INTERNAL_ERROR"
        assert call_kwargs["is_retryable"] is True

    @pytest.mark.asyncio
    @patch("doc_process_service.events.handlers.publish_processing_completed")
    @patch("doc_process_service.events.handlers._get_processing_service")
    @patch("doc_process_service.events.handlers.get_s3_client")
    async def test_sets_content_hash_on_result(
        self,
        mock_get_s3_client: MagicMock,
        mock_get_service: MagicMock,
        mock_publish_completed: AsyncMock,
        processing_params: ProcessingParams,
    ) -> None:
        """Test sets content hash on successful result."""
        mock_s3 = MagicMock()
        mock_s3.get_object = AsyncMock(return_value=b"document content")
        mock_get_s3_client.return_value = mock_s3

        mock_service = MagicMock()
        processed_snapshot = ProcessedDocumentSnapshot(
            content_id="content-abc",
            content_hash="",
            level=ProcessingLevel.TABLES,
            markdown="# Document",
        )
        mock_service.process = AsyncMock(return_value=ProcessingResult(content=processed_snapshot))
        mock_get_service.return_value = mock_service

        await _process_document(processing_params)

        call_args = mock_publish_completed.call_args[0]
        result_snapshot = call_args[1]
        assert result_snapshot.content_hash != ""

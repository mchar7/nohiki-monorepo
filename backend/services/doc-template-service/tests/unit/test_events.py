"""Tests for Kafka event handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from doc_template_service.core.auth_helpers import SYSTEM_SERVICE_UUID
from doc_template_service.events import start_event_consumer
from doc_template_service.events.commands import (
    handle_template_create_requested,
    handle_template_delete_requested,
    handle_template_version_add_requested,
)
from doc_template_service.events.render_handler import (
    RenderCompletedParams,
    _process_render_result,
    _publish_render_completed,
    _render_and_store,
    _render_output_format_to_content_type,
    _render_output_format_to_generator_format,
    _validate_render_request,
    handle_template_render_requested,
)
from doc_template_service.services.render_storage import StoredRenderResult
from doc_template_service.services.template_service import (
    TemplateDuplicateError,
    TemplateNotFoundError,
    TemplateVersionError,
)
from nohiki.common.v1 import AccessScope, EventMetadata, RenderOutputFormat
from nohiki.doc.template.v1 import TemplateAudience
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from nohiki_proto_google.protobuf import Struct


def _make_context(
    *,
    db: AsyncMock | None = None,
    outbox: AsyncMock | None = None,
) -> MessageContext:
    """Build a MessageContext with injected db session and outbox mocks."""
    ctx = MagicMock(spec=MessageContext)
    mock_db = db or AsyncMock()
    mock_outbox = outbox or AsyncMock()
    ctx.require_db_session.return_value = mock_db
    ctx.require_outbox.return_value = mock_outbox
    ctx.db_session = mock_db
    ctx.outbox = mock_outbox
    return ctx


class TestRenderOutputFormatToGeneratorFormat:
    """Tests for _render_output_format_to_generator_format function."""

    def test_unspecified_maps_to_html(self) -> None:
        """Test that unspecified format maps to HTML."""
        assert _render_output_format_to_generator_format(RenderOutputFormat.UNSPECIFIED) == "html"

    def test_html_format(self) -> None:
        """Test HTML format mapping."""
        assert _render_output_format_to_generator_format(RenderOutputFormat.HTML) == "html"

    def test_pdf_format(self) -> None:
        """Test PDF format mapping."""
        assert _render_output_format_to_generator_format(RenderOutputFormat.PDF) == "pdf"

    def test_image_format(self) -> None:
        """Test image format mapping."""
        assert _render_output_format_to_generator_format(RenderOutputFormat.IMAGE) == "image"

    def test_text_format(self) -> None:
        """Test text format mapping."""
        assert _render_output_format_to_generator_format(RenderOutputFormat.TEXT) == "text"


class TestRenderOutputFormatToContentType:
    """Tests for _render_output_format_to_content_type function."""

    def test_pdf_content_type(self) -> None:
        """Test PDF content type."""
        assert _render_output_format_to_content_type(RenderOutputFormat.PDF) == "application/pdf"

    def test_image_content_type(self) -> None:
        """Test image content type."""
        assert _render_output_format_to_content_type(RenderOutputFormat.IMAGE) == "image/png"

    def test_text_content_type(self) -> None:
        """Test text content type."""
        assert _render_output_format_to_content_type(RenderOutputFormat.TEXT) == "text/plain"

    def test_html_content_type(self) -> None:
        """Test HTML content type."""
        assert _render_output_format_to_content_type(RenderOutputFormat.HTML) == "text/html"

    def test_unspecified_defaults_to_html(self) -> None:
        """Test that unspecified format defaults to HTML content type."""
        assert _render_output_format_to_content_type(RenderOutputFormat.UNSPECIFIED) == "text/html"


class TestProcessRenderResult:
    """Tests for _process_render_result function."""

    def test_html_tuple_result(self) -> None:
        """Test processing HTML result with text alternative."""
        result = ("rendered html", "text alternative")
        content, text_alt = _process_render_result(result, "html")

        assert content == b"rendered html"
        assert text_alt == "text alternative"

    def test_bytes_result(self) -> None:
        """Test processing bytes result."""
        result = b"pdf content"
        content, text_alt = _process_render_result(result, "pdf")

        assert content == b"pdf content"
        assert text_alt == ""

    def test_string_result(self) -> None:
        """Test processing string result."""
        result = "text content"
        content, text_alt = _process_render_result(result, "text")

        assert content == b"text content"
        assert text_alt == ""

    def test_non_html_tuple_treated_as_string(self) -> None:
        """Test that tuple for non-HTML format is treated as string."""
        result = ("content", "alt")
        content, text_alt = _process_render_result(result, "pdf")

        assert b"content" in content
        assert text_alt == ""


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that function starts Kafka consumers."""
        with (
            patch("doc_template_service.events.logger") as mock_logger,
            patch("doc_template_service.events.kafka_client") as mock_kafka,
        ):
            start_event_consumer()

            mock_logger.info.assert_called_once()
            mock_kafka.start_consumers.assert_called_once()


class TestValidateRenderRequest:
    """Tests for _validate_render_request function."""

    def test_raises_error_when_metadata_missing(self) -> None:
        """ValidationError is raised when metadata is missing."""
        mock_message = MagicMock()
        mock_message.metadata = None

        with pytest.raises(ValidationError, match="metadata"):
            _validate_render_request(mock_message)

    def test_raises_error_when_correlation_id_missing(self) -> None:
        """ValidationError is raised when correlation_id is missing."""
        mock_message = MagicMock()
        mock_message.metadata = EventMetadata(
            event_id="test-id",
            correlation_id="",
            source_service="test",
        )

        with pytest.raises(ValidationError, match="correlation_id"):
            _validate_render_request(mock_message)

    def test_raises_error_when_template_content_missing(self) -> None:
        """ValidationError is raised when template_content is missing."""
        mock_message = MagicMock()
        mock_message.metadata = EventMetadata(
            event_id="test-id",
            correlation_id="corr-id",
            source_service="test",
        )
        mock_message.template_id = "template-123"
        mock_message.template_content = ""
        mock_message.template_version = "1.0.0"

        with pytest.raises(ValidationError, match="template_content"):
            _validate_render_request(mock_message)

    def test_raises_error_when_template_version_missing(self) -> None:
        """ValidationError is raised when template_version is missing."""
        mock_message = MagicMock()
        mock_message.metadata = EventMetadata(
            event_id="test-id",
            correlation_id="corr-id",
            source_service="test",
        )
        mock_message.template_id = "template-123"
        mock_message.template_content = "<html></html>"
        mock_message.template_version = ""

        with pytest.raises(ValidationError, match="template_version"):
            _validate_render_request(mock_message)

    def test_raises_error_when_template_version_is_not_semver(self) -> None:
        """ValidationError is raised for a nonempty invalid template version."""
        message = DocumentRenderRequested(
            metadata=EventMetadata(
                event_id="test-id",
                correlation_id="corr-id",
                source_service="test",
            ),
            template_id="template-123",
            template_content="<html></html>",
            template_version="not-a-version",
        )

        with pytest.raises(ValidationError, match="template_version") as exc_info:
            _validate_render_request(message)

        assert exc_info.value.field_name == "template_version"

    def test_accepts_valid_semver(self) -> None:
        """Valid semantic versions return the extracted request fields."""
        mock_message = MagicMock()
        mock_message.metadata = EventMetadata(
            event_id="test-id",
            correlation_id="corr-id",
            source_service="test",
        )
        mock_message.template_id = "template-123"
        mock_message.template_content = "<html></html>"
        mock_message.template_version = "1.0.0"

        result = _validate_render_request(mock_message)

        assert result == ("corr-id", "template-123", "1.0.0")


class TestRenderAndStore:
    """Tests for _render_and_store function."""

    @pytest.mark.asyncio
    async def test_renders_and_stores_document(self) -> None:
        """Test successful render and S3 storage."""
        mock_message = MagicMock()
        mock_message.output_format = RenderOutputFormat.PDF
        mock_message.include_text_alt = False
        mock_message.template_content = "<html>Test</html>"
        mock_message.data = Struct.from_dict({"key": "value"})

        mock_storage_result = StoredRenderResult(
            storage_key="rendered/corr/tmpl.pdf",
            file_size=1024,
            content_hash="abc123",
        )

        with (
            patch(
                "doc_template_service.events.render_handler.generate_document",
                new_callable=AsyncMock,
                return_value=b"PDF content",
            ),
            patch(
                "doc_template_service.events.render_handler.store_rendered_document",
                new_callable=AsyncMock,
                return_value=mock_storage_result,
            ) as mock_store,
        ):
            result = await _render_and_store(mock_message, "corr-id", "template-123")

            assert result[0] == "rendered/corr/tmpl.pdf"
            assert result[1] == "application/pdf"
            assert result[2] == 1024
            assert result[3] == "abc123"
            mock_store.assert_called_once()


class TestRenderCompletedParams:
    """Tests for RenderCompletedParams dataclass."""

    def test_dataclass_creation(self) -> None:
        """Test that dataclass can be created with all fields."""
        params = RenderCompletedParams(
            correlation_id="corr",
            template_id="tmpl",
            template_name="name",
            template_version="1.0.0",
            storage_key="key",
            content_type="application/pdf",
            file_size=100,
            content_hash="hash",
            text_alternative="alt",
        )

        assert params.correlation_id == "corr"
        assert params.template_id == "tmpl"
        assert params.file_size == 100


class TestHandleTemplateRenderRequested:
    """Tests for handle_template_render_requested event handler."""


    @pytest.mark.asyncio
    async def test_invalid_metadata_publishes_one_correlated_terminal_failure(
        self,
    ) -> None:
        """Invalid requests produce one schema-valid FAILED callback with no artifacts."""
        mock_message = MagicMock()
        mock_message.metadata = None
        mock_message.template_id = "template-123"
        mock_message.template_version = "1.0.0"
        mock_message.template_content = "<html>valid</html>"
        mock_outbox = AsyncMock()
        mock_context = _make_context(outbox=mock_outbox)
        mock_context.correlation_id = "corr-invalid"

        await handle_template_render_requested(mock_message, mock_context)

        mock_outbox.write_event.assert_awaited_once()
        event = mock_outbox.write_event.await_args.kwargs["event"]
        assert event.metadata.correlation_id == "corr-invalid"
        assert event.result.status.name == "FAILED"
        assert event.result.error.error_code == "RENDER_FAILED"
        assert event.storage_key == ""
        assert event.content_type == ""
        assert event.file_size == 0
        assert event.content_hash == ""
        assert event.text_alternative is None
        assert bytes(event)

    @pytest.mark.asyncio
    async def test_invalid_content_publishes_one_correlated_terminal_failure(
        self,
    ) -> None:
        """Missing template content produces exactly one terminal callback."""
        mock_message = MagicMock()
        mock_message.metadata = EventMetadata(
            event_id="test-id",
            correlation_id="corr-id",
            source_service="test",
        )
        mock_message.template_id = "template-123"
        mock_message.template_content = ""
        mock_message.template_version = "1.0.0"
        mock_outbox = AsyncMock()
        mock_context = _make_context(outbox=mock_outbox)

        await handle_template_render_requested(mock_message, mock_context)

        mock_outbox.write_event.assert_awaited_once()
        event = mock_outbox.write_event.await_args.kwargs["event"]
        assert event.metadata.correlation_id == "corr-id"
        assert event.result.status.name == "FAILED"
        assert event.storage_key == ""
        assert event.content_type == ""
        assert event.file_size == 0
        assert event.content_hash == ""
        assert event.text_alternative is None
        assert bytes(event)

    @pytest.mark.asyncio
    async def test_invalid_version_publishes_one_correlated_terminal_failure(
        self,
    ) -> None:
        """Missing template version produces exactly one terminal callback."""
        mock_message = MagicMock()
        mock_message.metadata = EventMetadata(
            event_id="test-id",
            correlation_id="corr-id",
            source_service="test",
        )
        mock_message.template_id = "template-123"
        mock_message.template_content = "<html>valid</html>"
        mock_message.template_version = ""
        mock_outbox = AsyncMock()
        mock_context = _make_context(outbox=mock_outbox)

        await handle_template_render_requested(mock_message, mock_context)

        mock_outbox.write_event.assert_awaited_once()
        event = mock_outbox.write_event.await_args.kwargs["event"]
        assert event.metadata.correlation_id == "corr-id"
        assert event.result.status.name == "FAILED"
        assert event.storage_key == ""
        assert event.content_type == ""
        assert event.file_size == 0
        assert event.content_hash == ""
        assert event.text_alternative is None
        assert bytes(event)

    @pytest.mark.asyncio
    async def test_successful_render_stores_and_publishes(self) -> None:
        """Test successful render stores to S3 and publishes via outbox."""
        mock_message = MagicMock()
        mock_message.metadata = EventMetadata(
            event_id="test-id",
            correlation_id="corr-id",
            source_service="test",
        )
        mock_message.template_id = "template-123"
        mock_message.template_content = "<html>{{ name }}</html>"
        mock_message.template_version = "1.0.0"
        mock_message.template_name = "test-template"
        mock_message.include_text_alt = False
        mock_message.data = Struct.from_dict({"name": "Test"})

        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_context = _make_context(db=mock_db, outbox=mock_outbox)

        mock_storage_result = StoredRenderResult(
            storage_key="rendered/corr-id/template-123.html",
            file_size=100,
            content_hash="a" * 64,
        )

        with (
            patch(
                "doc_template_service.events.render_handler.generate_document",
                new_callable=AsyncMock,
                return_value="<html>Test</html>",
            ),
            patch(
                "doc_template_service.events.render_handler.store_rendered_document",
                new_callable=AsyncMock,
                return_value=mock_storage_result,
            ) as mock_store,
        ):
            await handle_template_render_requested(mock_message, mock_context)

            mock_store.assert_called_once()
            mock_outbox.write_event.assert_awaited_once()
            mock_db.commit.assert_awaited_once()
            event = mock_outbox.write_event.await_args.kwargs["event"]
            assert event.metadata.correlation_id == "corr-id"
            assert event.storage_key == "rendered/corr-id/template-123.html"
            assert event.content_type == "text/html"
            assert event.file_size == 100
            assert event.content_hash == "a" * 64

    @pytest.mark.parametrize(
        ("storage_key", "content_type", "file_size", "content_hash"),
        [
            ("", "text/html", 100, "a" * 64),
            ("rendered/document.html", "", 100, "a" * 64),
            ("rendered/document.html", "text/html", 0, "a" * 64),
            ("rendered/document.html", "text/html", 100, "a" * 63),
        ],
    )
    @pytest.mark.asyncio
    async def test_successful_render_requires_artifact_metadata(
        self,
        storage_key: str,
        content_type: str,
        file_size: int,
        content_hash: str,
    ) -> None:
        """A COMPLETED callback cannot be emitted without persisted artifact metadata."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        params = RenderCompletedParams(
            correlation_id="corr-id",
            template_id="template-123",
            template_name="test-template",
            template_version="1.0.0",
            storage_key=storage_key,
            content_type=content_type,
            file_size=file_size,
            content_hash=content_hash,
            text_alternative="",
        )

        with pytest.raises(ValueError, match="valid artifact metadata"):
            await _publish_render_completed(mock_db, mock_outbox, params)

        mock_outbox.write_event.assert_not_awaited()


class TestHandleTemplateCreateRequested:
    """Tests for handle_template_create_requested event handler."""

    @pytest.mark.asyncio
    async def test_raises_error_when_namespace_missing(self) -> None:
        """Test that ValueError is raised when namespace is missing."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.name = "test-template"
        mock_message.namespace = ""
        mock_context = MagicMock()

        with pytest.raises(ValueError, match="namespace is required"):
            await handle_template_create_requested(mock_message, mock_context)

    @pytest.mark.asyncio
    async def test_successful_create(self) -> None:
        """Test successful template creation."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.name = "test-template"
        mock_message.display_name = "Test Template"
        mock_message.namespace = "default"
        mock_message.template_content = '<!-- TMPL_META {"access_scope": "PUBLIC"} --><html></html>'
        mock_message.description = "Test description"
        mock_message.content_schema_json = ""

        mock_template = MagicMock()
        mock_template.id = "template-123"
        mock_template.name = "test-template"
        mock_template.version = "1.0.0"

        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.create_template",
                new_callable=AsyncMock,
                return_value=mock_template,
            ),
            patch(
                "doc_template_service.events.commands.publish_template_created_event",
                new_callable=AsyncMock,
            ),
        ):
            await handle_template_create_requested(mock_message, mock_context)


class TestHandleTemplateVersionAddRequested:
    """Tests for handle_template_version_add_requested event handler."""

    @pytest.mark.asyncio
    async def test_successful_version_add(self) -> None:
        """Test successful template version addition."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.template_id = "22222222-2222-2222-2222-222222222222"
        mock_message.version = "2.0.0"
        mock_message.template_content = '<!-- TMPL_META {"access_scope": "PUBLIC"} --><html></html>'
        mock_message.description = "New version"
        mock_message.content_schema_json = ""

        mock_source_template = MagicMock()
        mock_source_template.name = "test-template"
        mock_source_template.display_name = "Test Template"
        mock_source_template.namespace = "default"
        mock_source_template.access_scope = AccessScope.PRIVATE
        mock_source_template.owner_id = UUID(mock_message.user_id)
        mock_source_template.audience = TemplateAudience.DOCUMENT

        mock_new_template = MagicMock()
        mock_new_template.id = "33333333-3333-3333-3333-333333333333"
        mock_new_template.version = "2.0.0"

        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.get_template_model_by_id",
                new_callable=AsyncMock,
                return_value=mock_source_template,
            ),
            patch(
                "doc_template_service.events.commands.create_template",
                new_callable=AsyncMock,
                return_value=mock_new_template,
            ) as mock_create,
            patch(
                "doc_template_service.events.commands.publish_template_updated_event",
                new_callable=AsyncMock,
            ),
        ):
            await handle_template_version_add_requested(mock_message, mock_context)

        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_regular_user_public_source_is_reported_not_found(self) -> None:
        """A regular user cannot replace the globally latest public template."""
        mock_message = MagicMock()
        mock_message.request_id = "req-public"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.template_id = "22222222-2222-2222-2222-222222222222"
        mock_message.version = "2.0.0"
        mock_message.template_content = "<html>unauthorized public version</html>"
        mock_message.description = "Unauthorized version"
        mock_message.content_schema_json = ""

        mock_source_template = MagicMock()
        mock_source_template.access_scope = AccessScope.PUBLIC
        mock_source_template.owner_id = None
        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.get_template_model_by_id",
                new_callable=AsyncMock,
                return_value=mock_source_template,
            ),
            patch(
                "doc_template_service.events.commands.create_template",
                new_callable=AsyncMock,
            ) as mock_create,
            pytest.raises(TemplateNotFoundError, match=mock_message.template_id),
        ):
            await handle_template_version_add_requested(mock_message, mock_context)

        mock_create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_system_service_can_add_public_version(self) -> None:
        """The system service can publish a new version of a public template."""
        mock_message = MagicMock()
        mock_message.request_id = "req-system-public"
        mock_message.user_id = str(SYSTEM_SERVICE_UUID)
        mock_message.template_id = "22222222-2222-2222-2222-222222222222"
        mock_message.version = "2.0.0"
        mock_message.template_content = "<html>authorized public version</html>"
        mock_message.description = "Authorized version"
        mock_message.content_schema_json = ""

        mock_source_template = MagicMock()
        mock_source_template.name = "public-template"
        mock_source_template.display_name = "Public Template"
        mock_source_template.namespace = "default"
        mock_source_template.access_scope = AccessScope.PUBLIC
        mock_source_template.owner_id = None
        mock_source_template.audience = TemplateAudience.DOCUMENT
        mock_new_template = MagicMock()
        mock_new_template.id = "33333333-3333-3333-3333-333333333333"
        mock_new_template.version = "2.0.0"
        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.get_template_model_by_id",
                new_callable=AsyncMock,
                return_value=mock_source_template,
            ),
            patch(
                "doc_template_service.events.commands.create_template",
                new_callable=AsyncMock,
                return_value=mock_new_template,
            ) as mock_create,
            patch(
                "doc_template_service.events.commands.publish_template_updated_event",
                new_callable=AsyncMock,
            ),
        ):
            await handle_template_version_add_requested(mock_message, mock_context)

        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cross_user_private_source_is_reported_not_found(self) -> None:
        """A user cannot add a version derived from another user's private template."""
        mock_message = MagicMock()
        mock_message.request_id = "req-private"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.template_id = "22222222-2222-2222-2222-222222222222"
        mock_message.version = "2.0.0"
        mock_message.template_content = "<html>stolen source</html>"
        mock_message.description = "Unauthorized version"
        mock_message.content_schema_json = ""

        mock_source_template = MagicMock()
        mock_source_template.access_scope = AccessScope.PRIVATE
        mock_source_template.owner_id = UUID("99999999-9999-9999-9999-999999999999")
        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.get_template_model_by_id",
                new_callable=AsyncMock,
                return_value=mock_source_template,
            ),
            patch(
                "doc_template_service.events.commands.create_template",
                new_callable=AsyncMock,
            ) as mock_create,
            pytest.raises(TemplateNotFoundError, match=mock_message.template_id),
        ):
            await handle_template_version_add_requested(mock_message, mock_context)

        mock_create.assert_not_awaited()


class TestHandleTemplateDeleteRequested:
    """Tests for handle_template_delete_requested event handler."""

    @pytest.mark.asyncio
    async def test_successful_delete(self) -> None:
        """Test successful template deletion."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.template_id = "22222222-2222-2222-2222-222222222222"

        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.delete_template",
                new_callable=AsyncMock,
            ),
            patch(
                "doc_template_service.events.commands.publish_template_deleted_event",
                new_callable=AsyncMock,
            ),
        ):
            await handle_template_delete_requested(mock_message, mock_context)


class TestHandleTemplateCreateRequestedExceptions:
    """Tests for exception handling in handle_template_create_requested."""

    @pytest.mark.asyncio
    async def test_handles_duplicate_error(self) -> None:
        """Test that duplicate template error is handled gracefully."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.name = "duplicate-template"
        mock_message.display_name = "Duplicate Template"
        mock_message.namespace = "default"
        mock_message.template_content = '<!-- TMPL_META {"access_scope": "PUBLIC"} --><html></html>'
        mock_message.description = "Test description"
        mock_message.content_schema_json = ""
        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.create_template",
                new_callable=AsyncMock,
                side_effect=TemplateDuplicateError("duplicate-template", "1.0.0"),
            ),
            patch("doc_template_service.events.commands.logger") as mock_logger,
        ):
            await handle_template_create_requested(mock_message, mock_context)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "duplicate" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_handles_version_error(self) -> None:
        """Test that version validation error is handled gracefully."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.name = "invalid-version-template"
        mock_message.display_name = "Invalid Version Template"
        mock_message.namespace = "default"
        mock_message.template_content = '<!-- TMPL_META {"access_scope": "PUBLIC"} --><html></html>'
        mock_message.description = "Test description"
        mock_message.content_schema_json = ""
        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.create_template",
                new_callable=AsyncMock,
                side_effect=TemplateVersionError("Invalid version format"),
            ),
            patch("doc_template_service.events.commands.logger") as mock_logger,
        ):
            await handle_template_create_requested(mock_message, mock_context)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "validation error" in call_args[0][0].lower()


class TestHandleTemplateVersionAddRequestedExceptions:
    """Tests for exception handling in handle_template_version_add_requested."""

    @pytest.mark.asyncio
    async def test_raises_not_found_error(self) -> None:
        """Test that not found error is raised when source template not found."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.template_id = "22222222-2222-2222-2222-222222222222"
        mock_message.version = "2.0.0"
        mock_message.template_content = '<!-- TMPL_META {"access_scope": "PUBLIC"} --><html></html>'
        mock_message.description = "New version"
        mock_message.content_schema_json = ""
        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.get_template_model_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("doc_template_service.events.commands.logger"),
            pytest.raises(TemplateNotFoundError),
        ):
            await handle_template_version_add_requested(mock_message, mock_context)

    @pytest.mark.asyncio
    async def test_raises_duplicate_error(self) -> None:
        """Test that duplicate version error is re-raised."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.template_id = "22222222-2222-2222-2222-222222222222"
        mock_message.version = "1.0.0"
        mock_message.template_content = '<!-- TMPL_META {"access_scope": "PUBLIC"} --><html></html>'
        mock_message.description = "Duplicate version"
        mock_message.content_schema_json = ""

        mock_source_template = MagicMock()
        mock_source_template.name = "test-template"
        mock_source_template.display_name = "Test Template"
        mock_source_template.namespace = "default"
        mock_source_template.access_scope = AccessScope.PRIVATE
        mock_source_template.owner_id = UUID(mock_message.user_id)
        mock_source_template.audience = TemplateAudience.DOCUMENT

        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.get_template_model_by_id",
                new_callable=AsyncMock,
                return_value=mock_source_template,
            ),
            patch(
                "doc_template_service.events.commands.create_template",
                new_callable=AsyncMock,
                side_effect=TemplateDuplicateError("test-template", "1.0.0"),
            ),
            patch("doc_template_service.events.commands.logger"),
            pytest.raises(TemplateDuplicateError),
        ):
            await handle_template_version_add_requested(mock_message, mock_context)

    @pytest.mark.asyncio
    async def test_raises_version_error(self) -> None:
        """Test that version validation error is re-raised."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.template_id = "22222222-2222-2222-2222-222222222222"
        mock_message.version = "invalid"
        mock_message.template_content = '<!-- TMPL_META {"access_scope": "PUBLIC"} --><html></html>'
        mock_message.description = "Invalid version"
        mock_message.content_schema_json = ""

        mock_source_template = MagicMock()
        mock_source_template.name = "test-template"
        mock_source_template.display_name = "Test Template"
        mock_source_template.namespace = "default"
        mock_source_template.access_scope = AccessScope.PRIVATE
        mock_source_template.owner_id = UUID(mock_message.user_id)
        mock_source_template.audience = TemplateAudience.DOCUMENT

        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.get_template_model_by_id",
                new_callable=AsyncMock,
                return_value=mock_source_template,
            ),
            patch(
                "doc_template_service.events.commands.create_template",
                new_callable=AsyncMock,
                side_effect=TemplateVersionError("Invalid version"),
            ),
            patch("doc_template_service.events.commands.logger"),
            pytest.raises(TemplateVersionError),
        ):
            await handle_template_version_add_requested(mock_message, mock_context)


class TestHandleTemplateDeleteRequestedExceptions:
    """Tests for exception handling in handle_template_delete_requested."""

    @pytest.mark.asyncio
    async def test_handles_not_found_error_gracefully(self) -> None:
        """Test that not found error is handled gracefully (idempotent delete)."""
        mock_message = MagicMock()
        mock_message.request_id = "req-123"
        mock_message.user_id = "11111111-1111-1111-1111-111111111111"
        mock_message.template_id = "22222222-2222-2222-2222-222222222222"
        mock_context = _make_context()

        with (
            patch(
                "doc_template_service.events.commands.delete_template",
                new_callable=AsyncMock,
                side_effect=TemplateNotFoundError("Layout not found"),
            ),
            patch("doc_template_service.events.commands.logger") as mock_logger,
        ):
            await handle_template_delete_requested(mock_message, mock_context)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "not found" in call_args[0][0].lower()

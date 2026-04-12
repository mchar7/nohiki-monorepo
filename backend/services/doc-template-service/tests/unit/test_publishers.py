"""Tests for template event publishers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from doc_template_service.events.publishers import (
    AGGREGATE_TYPE,
    build_template_snapshot,
    publish_template_created_event,
    publish_template_deleted_event,
    publish_template_updated_event,
)
from nohiki.common.v1 import AccessScope
from nohiki.doc.template.v1 import (
    DocumentTemplateVersionSnapshot,
    TemplateCreated,
    TemplateDeleted,
    TemplateUpdated,
)
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import Topics


class TestBuildTemplateSnapshot:
    """Tests for build_template_snapshot function."""

    def test_builds_snapshot_with_all_fields(self) -> None:
        """Test building snapshot with all fields populated."""
        mock_template = MagicMock()
        mock_template.id = "template-123"
        mock_template.namespace = "default"
        mock_template.name = "Test Template"
        mock_template.display_name = "Test Template"
        mock_template.version = "1.0.0"
        mock_template.template_content = "<html>{{ name }}</html>"
        mock_template.content_schema = {"type": "object"}
        mock_template.description = "Test description"
        mock_template.access_scope = MagicMock()
        mock_template.access_scope.name = "PUBLIC"
        mock_template.owner_id = "owner-456"

        snapshot = build_template_snapshot(mock_template)

        assert snapshot.id == "template-123"
        assert snapshot.namespace == "default"
        assert snapshot.name == "Test Template"
        assert snapshot.display_name == "Test Template"
        assert snapshot.access_scope == AccessScope.PUBLIC
        assert snapshot.owner_id == "owner-456"
        assert snapshot.latest_version == "1.0.0"
        assert snapshot.description == "Test description"
        assert isinstance(snapshot.version_snapshot, DocumentTemplateVersionSnapshot)
        assert snapshot.version_snapshot.version_id == "template-123"
        assert snapshot.version_snapshot.version == "1.0.0"
        assert snapshot.version_snapshot.template_content == "<html>{{ name }}</html>"

    def test_builds_snapshot_with_optional_fields(self) -> None:
        """Test building snapshot with optional fields as None."""
        mock_template = MagicMock()
        mock_template.id = "template-789"
        mock_template.namespace = "custom"
        mock_template.name = "Custom Template"
        mock_template.display_name = "Custom Template"
        mock_template.version = "2.0.0"
        mock_template.template_content = "<div>Content</div>"
        mock_template.content_schema = None
        mock_template.description = None
        mock_template.access_scope = MagicMock()
        mock_template.access_scope.name = "PRIVATE"
        mock_template.owner_id = None

        snapshot = build_template_snapshot(mock_template)

        assert snapshot.id == "template-789"
        assert snapshot.namespace == "custom"
        assert snapshot.name == "Custom Template"
        assert snapshot.display_name == "Custom Template"
        assert snapshot.access_scope == AccessScope.PRIVATE
        assert snapshot.owner_id == ""
        assert snapshot.description == ""
        assert snapshot.version_snapshot.content_schema_json == ""

    def test_builds_snapshot_with_empty_content_schema(self) -> None:
        """Test building snapshot with empty content_schema."""
        mock_template = MagicMock()
        mock_template.id = "template-000"
        mock_template.namespace = "default"
        mock_template.name = "Empty Schema"
        mock_template.version = "1.0.0"
        mock_template.display_name = "Empty Schema"
        mock_template.template_content = "<html></html>"
        mock_template.content_schema = {}
        mock_template.description = ""
        mock_template.access_scope = MagicMock()
        mock_template.access_scope.name = "PUBLIC"
        mock_template.owner_id = None

        snapshot = build_template_snapshot(mock_template)

        assert snapshot.version_snapshot.content_schema_json == ""


class TestPublishTemplateCreatedEvent:
    """Tests for publish_template_created_event function."""

    @pytest.mark.asyncio
    async def test_publishes_created_event_with_snapshot(self) -> None:
        """Test that created event is published with full snapshot."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event = AsyncMock(return_value="event-123")

        mock_template = MagicMock()
        mock_template.id = "template-123"
        mock_template.namespace = "default"
        mock_template.name = "Test Template"
        mock_template.display_name = "Test Template"
        mock_template.version = "1.0.0"
        mock_template.template_content = "<html>{{ name }}</html>"
        mock_template.content_schema = {"type": "object"}
        mock_template.description = "Test description"
        mock_template.access_scope = MagicMock()
        mock_template.access_scope.name = "PUBLIC"
        mock_template.owner_id = "owner-456"

        with patch("doc_template_service.events.publishers.logger") as mock_logger:
            await publish_template_created_event(mock_db, mock_outbox, mock_template)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs

        assert call_kwargs["db"] == mock_db
        assert call_kwargs["params"].aggregate_type == AGGREGATE_TYPE
        assert call_kwargs["params"].aggregate_id == "template-123"
        assert call_kwargs["params"].event_type == Topics.DOC_TEMPLATE_CREATED

        event = call_kwargs["event"]
        assert isinstance(event, TemplateCreated)
        assert event.template_id == "template-123"
        assert event.template_snapshot.namespace == "default"
        assert event.template_snapshot.name == "Test Template"
        assert event.template_snapshot.display_name == "Test Template"

        mock_logger.info.assert_called_once()
        log_call = mock_logger.info.call_args[0][0]
        assert "Published template created event" in log_call


class TestPublishTemplateUpdatedEvent:
    """Tests for publish_template_updated_event function."""

    @pytest.mark.asyncio
    async def test_publishes_updated_event_with_snapshot(self) -> None:
        """Test that updated event is published with full snapshot."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event = AsyncMock(return_value="event-456")

        mock_template = MagicMock()
        mock_template.id = "template-789"
        mock_template.namespace = "custom"
        mock_template.name = "Updated Template"
        mock_template.display_name = "Updated Template"
        mock_template.version = "2.0.0"
        mock_template.template_content = "<div>New content</div>"
        mock_template.content_schema = {"type": "object"}
        mock_template.description = "Updated description"
        mock_template.access_scope = MagicMock()
        mock_template.access_scope.name = "PRIVATE"
        mock_template.owner_id = "owner-789"

        with patch("doc_template_service.events.publishers.logger") as mock_logger:
            await publish_template_updated_event(mock_db, mock_outbox, mock_template)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs

        assert call_kwargs["params"].event_type == Topics.DOC_TEMPLATE_UPDATED

        event = call_kwargs["event"]
        assert isinstance(event, TemplateUpdated)
        assert event.template_id == "template-789"
        assert event.template_snapshot.namespace == "custom"
        assert event.template_snapshot.name == "Updated Template"
        assert event.template_snapshot.display_name == "Updated Template"

        mock_logger.info.assert_called_once()
        log_call = mock_logger.info.call_args[0]
        assert "Published template updated event" in log_call[0]


class TestPublishTemplateDeletedEvent:
    """Tests for publish_template_deleted_event function."""

    @pytest.mark.asyncio
    async def test_publishes_deleted_event_with_id_only(self) -> None:
        """Test that deleted event is published with template ID only."""
        mock_db = create_mock_session()
        mock_outbox = AsyncMock()
        mock_outbox.write_event = AsyncMock(return_value="event-999")

        template_id = "template-999"

        with patch("doc_template_service.events.publishers.logger") as mock_logger:
            await publish_template_deleted_event(mock_db, mock_outbox, template_id)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs

        assert call_kwargs["params"].aggregate_type == AGGREGATE_TYPE
        assert call_kwargs["params"].aggregate_id == "template-999"
        assert call_kwargs["params"].event_type == Topics.DOC_TEMPLATE_DELETED

        event = call_kwargs["event"]
        assert isinstance(event, TemplateDeleted)
        assert event.template_id == "template-999"

        mock_logger.info.assert_called_once()
        log_call = mock_logger.info.call_args[0][0]
        assert "Published template deleted event" in log_call

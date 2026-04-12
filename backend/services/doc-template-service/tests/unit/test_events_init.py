"""Unit tests for events/__init__.py module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that start_event_consumer starts Kafka consumers."""
        with (
            patch("doc_template_service.events.kafka_client") as mock_kafka,
            patch("doc_template_service.events.logger") as mock_logger,
        ):
            mock_kafka.start_consumers = MagicMock()

            from doc_template_service.events import start_event_consumer

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()
            mock_logger.info.assert_called()

    def test_logs_service_name_on_start(self) -> None:
        """Test that start_event_consumer logs the service name."""
        with (
            patch("doc_template_service.events.kafka_client") as mock_kafka,
            patch("doc_template_service.events.logger") as mock_logger,
            patch("doc_template_service.events.settings") as mock_settings,
        ):
            mock_kafka.start_consumers = MagicMock()
            mock_settings.service_name = "doc-template-service"

            from doc_template_service.events import start_event_consumer

            start_event_consumer()

            mock_logger.info.assert_called_with(
                "Starting event consumer",
                service="doc-template-service",
            )


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_commands_module(self) -> None:
        """Test that commands module is exported."""
        from doc_template_service.events import commands

        assert commands is not None

    def test_exports_render_handler_module(self) -> None:
        """Test that render_handler module is exported."""
        from doc_template_service.events import render_handler

        assert render_handler is not None

    def test_exports_start_event_consumer(self) -> None:
        """Test that start_event_consumer is exported."""
        from doc_template_service.events import start_event_consumer

        assert callable(start_event_consumer)

    def test_all_contains_expected_exports(self) -> None:
        """Test that __all__ contains all expected exports."""
        from doc_template_service.events import __all__

        expected = [
            "build_template_snapshot",
            "commands",
            "publish_template_created_event",
            "publish_template_deleted_event",
            "publish_template_updated_event",
            "render_handler",
            "start_event_consumer",
        ]

        for export in expected:
            assert export in __all__, f"{export} missing from __all__"

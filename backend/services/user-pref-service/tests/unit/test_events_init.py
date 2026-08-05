"""Unit tests for events/__init__.py module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that start_event_consumer starts Kafka consumers."""
        with (
            patch("user_pref_service.events.kafka_client") as mock_kafka,
            patch("user_pref_service.events.logger") as mock_logger,
        ):
            mock_kafka.start_consumers = MagicMock()

            from user_pref_service.events import start_event_consumer

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()
            mock_logger.info.assert_called()

    def test_logs_service_name_on_start(self) -> None:
        """Test that start_event_consumer logs the service name."""
        with (
            patch("user_pref_service.events.kafka_client") as mock_kafka,
            patch("user_pref_service.events.logger") as mock_logger,
            patch("user_pref_service.events.settings") as mock_settings,
        ):
            mock_kafka.start_consumers = MagicMock()
            mock_settings.service_name = "user-pref-service"

            from user_pref_service.events import start_event_consumer

            start_event_consumer()

            mock_logger.info.assert_called_with(
                "Starting event consumer",
                service="user-pref-service",
            )


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_callbacks_module(self) -> None:
        """Test that callbacks module is exported."""
        from user_pref_service.events import callbacks

        assert callbacks is not None

    def test_exports_commands_module(self) -> None:
        """Test that commands module is exported."""
        from user_pref_service.events import commands

        assert commands is not None

    def test_exports_qdrant_handlers_module(self) -> None:
        """Importing events registers committed Qdrant projection handlers."""
        from user_pref_service.events import qdrant_handlers

        assert callable(qdrant_handlers.handle_pref_created)
        assert callable(qdrant_handlers.handle_pref_updated)
        assert callable(qdrant_handlers.handle_pref_deleted)

    def test_exports_upstream_cdc_module(self) -> None:
        """Test that upstream_cdc module is exported."""
        from user_pref_service.events import upstream_cdc

        assert upstream_cdc is not None

    def test_exports_start_event_consumer(self) -> None:
        """Test that start_event_consumer is exported."""
        from user_pref_service.events import start_event_consumer

        assert callable(start_event_consumer)

    def test_all_contains_expected_exports(self) -> None:
        """Test that __all__ contains all expected exports."""
        from user_pref_service.events import __all__

        expected = ["callbacks", "commands", "qdrant_handlers", "start_event_consumer", "upstream_cdc"]

        for export in expected:
            assert export in __all__, f"{export} missing from __all__"

"""Unit tests for events/__init__.py module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that start_event_consumer starts Kafka consumers."""
        with (
            patch("user_entitlement_service.events.handlers.kafka_client") as mock_kafka,
            patch("user_entitlement_service.events.handlers.logger") as mock_logger,
            patch("user_entitlement_service.events.handlers.settings") as mock_settings,
        ):
            mock_kafka.start_consumers = MagicMock()
            mock_settings.service_name = "user-entitlement-service"

            from user_entitlement_service.events import start_event_consumer

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()
            mock_logger.info.assert_called_with(
                "Starting event consumer",
                service="user-entitlement-service",
            )


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_start_event_consumer(self) -> None:
        """Test that start_event_consumer is exported."""
        from user_entitlement_service.events import start_event_consumer

        assert callable(start_event_consumer)

    def test_all_contains_expected_exports(self) -> None:
        """Test that __all__ contains all expected exports."""
        from user_entitlement_service.events import __all__

        expected = ["handlers", "start_event_consumer"]

        for export in expected:
            assert export in __all__, f"{export} missing from __all__"

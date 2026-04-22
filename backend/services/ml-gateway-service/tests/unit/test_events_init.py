"""Unit tests for events/__init__.py module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that start_event_consumer starts Kafka consumers."""
        with (
            patch("ml_gateway_service.events.kafka_client") as mock_kafka,
            patch("ml_gateway_service.events.logger") as mock_logger,
        ):
            mock_kafka.start_consumers = MagicMock()

            from ml_gateway_service.events import start_event_consumer

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()
            mock_logger.info.assert_called()

    def test_logs_service_name_on_start(self) -> None:
        """Test that start_event_consumer logs the service name."""
        with (
            patch("ml_gateway_service.events.kafka_client") as mock_kafka,
            patch("ml_gateway_service.events.logger") as mock_logger,
            patch("ml_gateway_service.events.settings") as mock_settings,
        ):
            mock_kafka.start_consumers = MagicMock()
            mock_settings.service_name = "ml-gateway-service"

            from ml_gateway_service.events import start_event_consumer

            start_event_consumer()

            mock_logger.info.assert_called_with(
                "Starting event consumer",
                service="ml-gateway-service",
            )


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_embedding_module(self) -> None:
        """Test that embedding module is exported."""
        from ml_gateway_service.events import embedding

        assert embedding is not None

    def test_exports_rerank_module(self) -> None:
        """Test that rerank module is exported."""
        from ml_gateway_service.events import rerank

        assert rerank is not None

    def test_exports_start_event_consumer(self) -> None:
        """Test that start_event_consumer is exported."""
        from ml_gateway_service.events import start_event_consumer

        assert callable(start_event_consumer)

    def test_all_contains_expected_exports(self) -> None:
        """Test that __all__ contains all expected exports."""
        from ml_gateway_service.events import __all__

        expected = ["embedding", "rerank", "start_event_consumer"]

        for export in expected:
            assert export in __all__, f"{export} missing from __all__"

"""Unit tests for events/__init__.py module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that start_event_consumer starts Kafka consumers."""
        with patch("job_ingest_enrichment_service.events.handlers.kafka_client") as mock_kafka:
            mock_kafka.start_consumers = MagicMock()

            from job_ingest_enrichment_service.events import start_event_consumer

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_start_event_consumer(self) -> None:
        """Test that start_event_consumer is exported."""
        from job_ingest_enrichment_service.events import start_event_consumer

        assert callable(start_event_consumer)

    def test_all_contains_start_event_consumer(self) -> None:
        """Test that __all__ contains start_event_consumer."""
        from job_ingest_enrichment_service.events import __all__

        assert "start_event_consumer" in __all__

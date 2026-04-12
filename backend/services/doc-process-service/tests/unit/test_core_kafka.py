"""Tests for doc_process_service.core.kafka module."""

from __future__ import annotations

from doc_process_service.core.kafka import kafka_client


class TestKafkaClient:
    """Tests for kafka client singleton."""

    def test_kafka_client_exists(self) -> None:
        """Test that kafka_client module-level instance exists."""
        assert kafka_client is not None

    def test_kafka_client_is_singleton(self) -> None:
        """Test kafka_client is a singleton module-level instance."""
        from doc_process_service.core.kafka import kafka_client as reimport

        assert reimport is kafka_client

    def test_kafka_client_has_required_methods(self) -> None:
        """Test kafka client has required interface methods."""
        assert hasattr(kafka_client, "start_consumers")
        assert hasattr(kafka_client, "stop_consumers")
        assert hasattr(kafka_client, "close")
        assert hasattr(kafka_client, "message_handler")
        assert hasattr(kafka_client, "publish")

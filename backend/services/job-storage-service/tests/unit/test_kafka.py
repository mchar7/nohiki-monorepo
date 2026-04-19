"""Unit tests for core/kafka.py module."""

from __future__ import annotations


class TestKafkaClient:
    """Tests for kafka_client module-level singleton."""

    def test_kafka_client_is_available(self) -> None:
        """Test that kafka_client is importable and available."""
        from job_storage_service.core.kafka import kafka_client

        assert kafka_client is not None

    def test_kafka_client_has_expected_methods(self) -> None:
        """Test that kafka_client has expected methods."""
        from job_storage_service.core.kafka import kafka_client

        assert hasattr(kafka_client, "publish")
        assert hasattr(kafka_client, "message_handler")

"""Unit tests for core/kafka.py module."""

from __future__ import annotations


class TestKafkaClient:
    """Tests for kafka_client module-level instance."""

    def test_kafka_client_is_created(self) -> None:
        """Test that kafka_client is created at module level."""
        from job_ingest_schedule_service.core.kafka import kafka_client

        assert kafka_client is not None

    def test_kafka_client_has_expected_attributes(self) -> None:
        """Test that kafka_client has expected AutoKafkaClient attributes."""
        from job_ingest_schedule_service.core.kafka import kafka_client

        assert hasattr(kafka_client, "message_handler")
        assert hasattr(kafka_client, "start_consumers")
        assert hasattr(kafka_client, "stop_consumers")

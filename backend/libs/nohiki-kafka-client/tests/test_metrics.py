"""Unit tests for KafkaMetrics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestKafkaMetrics:
    """Tests for KafkaMetrics class."""

    def test_init_creates_all_instruments(self) -> None:
        """KafkaMetrics creates all metric instruments."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics") as mock_metrics:
            mock_meter = MagicMock()
            mock_metrics.get_meter.return_value = mock_meter

            metrics = KafkaMetrics()

            mock_metrics.get_meter.assert_called_once_with("nohiki.kafka")
            assert mock_meter.create_counter.call_count == 5
            assert mock_meter.create_histogram.call_count == 2
            assert mock_meter.create_up_down_counter.call_count == 1

            assert metrics.messages_produced is not None
            assert metrics.messages_consumed is not None
            assert metrics.publish_duration is not None
            assert metrics.processing_duration is not None
            assert metrics.consumer_lag is not None
            assert metrics.dlq_messages is not None
            assert metrics.errors is not None
            assert metrics.retries is not None

    def test_record_message_produced_success(self) -> None:
        """record_message_produced records success metrics."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics"):
            metrics = KafkaMetrics()
            metrics.messages_produced = MagicMock()
            metrics.publish_duration = MagicMock()
            metrics.errors = MagicMock()

            metrics.record_message_produced("test-topic", 0.5, success=True)

            metrics.messages_produced.add.assert_called_once()
            metrics.publish_duration.record.assert_called_once()
            metrics.errors.add.assert_not_called()

    def test_record_message_produced_with_partition(self) -> None:
        """record_message_produced includes partition when provided."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics"):
            metrics = KafkaMetrics()
            metrics.messages_produced = MagicMock()
            metrics.publish_duration = MagicMock()
            metrics.errors = MagicMock()

            metrics.record_message_produced("test-topic", 0.5, partition=3)

            call_args = metrics.messages_produced.add.call_args
            attrs = call_args[0][1]
            assert attrs["partition"] == 3

    def test_record_message_produced_failure(self) -> None:
        """record_message_produced records error on failure."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics"):
            metrics = KafkaMetrics()
            metrics.messages_produced = MagicMock()
            metrics.publish_duration = MagicMock()
            metrics.errors = MagicMock()

            metrics.record_message_produced("test-topic", 0.5, success=False)

            metrics.errors.add.assert_called_once_with(1, {"topic": "test-topic", "operation": "produce"})

    def test_record_message_consumed_success(self) -> None:
        """record_message_consumed records success metrics."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics"):
            metrics = KafkaMetrics()
            metrics.messages_consumed = MagicMock()
            metrics.processing_duration = MagicMock()
            metrics.errors = MagicMock()

            metrics.record_message_consumed("test-topic", "test-group", 0.3, success=True)

            metrics.messages_consumed.add.assert_called_once()
            metrics.processing_duration.record.assert_called_once()
            metrics.errors.add.assert_not_called()

    def test_record_message_consumed_with_handler(self) -> None:
        """record_message_consumed includes handler when provided."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics"):
            metrics = KafkaMetrics()
            metrics.messages_consumed = MagicMock()
            metrics.processing_duration = MagicMock()
            metrics.errors = MagicMock()

            metrics.record_message_consumed("test-topic", "test-group", 0.3, handler="my_handler")

            call_args = metrics.messages_consumed.add.call_args
            attrs = call_args[0][1]
            assert attrs["handler"] == "my_handler"

    def test_record_message_consumed_failure(self) -> None:
        """record_message_consumed records error on failure."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics"):
            metrics = KafkaMetrics()
            metrics.messages_consumed = MagicMock()
            metrics.processing_duration = MagicMock()
            metrics.errors = MagicMock()

            metrics.record_message_consumed("test-topic", "test-group", 0.3, success=False)

            metrics.errors.add.assert_called_once_with(1, {"topic": "test-topic", "operation": "consume"})

    def test_record_dlq_message(self) -> None:
        """record_dlq_message records DLQ metrics."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics"):
            metrics = KafkaMetrics()
            metrics.dlq_messages = MagicMock()

            metrics.record_dlq_message("test-topic", "test-group", "max_retries")

            metrics.dlq_messages.add.assert_called_once_with(
                1,
                {
                    "topic": "test-topic",
                    "consumer_group": "test-group",
                    "reason": "max_retries",
                },
            )

    def test_record_retry(self) -> None:
        """record_retry records retry metrics."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics"):
            metrics = KafkaMetrics()
            metrics.retries = MagicMock()

            metrics.record_retry("test-topic", "test-group", 3)

            metrics.retries.add.assert_called_once_with(
                1,
                {
                    "topic": "test-topic",
                    "consumer_group": "test-group",
                    "attempt": "3",
                },
            )

    def test_update_consumer_lag(self) -> None:
        """update_consumer_lag records consumer lag."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics

        with patch("nohiki_kafka_client.observability.metrics.metrics"):
            metrics = KafkaMetrics()
            metrics.consumer_lag = MagicMock()

            metrics.update_consumer_lag("test-topic", "test-group", 2, 100)

            metrics.consumer_lag.add.assert_called_once_with(
                100,
                {
                    "topic": "test-topic",
                    "consumer_group": "test-group",
                    "partition": "2",
                },
            )


class TestGetKafkaMetrics:
    """Tests for get_kafka_metrics singleton."""

    def test_returns_same_instance(self) -> None:
        """get_kafka_metrics returns singleton."""
        from nohiki_kafka_client.observability.metrics import get_kafka_metrics

        get_kafka_metrics.cache_clear()

        instance1 = get_kafka_metrics()
        instance2 = get_kafka_metrics()

        assert instance1 is instance2

    def test_returns_kafka_metrics_instance(self) -> None:
        """get_kafka_metrics returns KafkaMetrics."""
        from nohiki_kafka_client.observability.metrics import KafkaMetrics, get_kafka_metrics

        get_kafka_metrics.cache_clear()

        instance = get_kafka_metrics()

        assert isinstance(instance, KafkaMetrics)

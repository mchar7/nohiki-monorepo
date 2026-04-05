"""Kafka metrics - owned by nohiki-kafka-client."""

from __future__ import annotations

from functools import lru_cache

from opentelemetry import metrics


class KafkaMetrics:
    """Kafka producer/consumer metrics using OpenTelemetry."""

    def __init__(self) -> None:
        """Initialize Kafka metrics with OpenTelemetry meter."""
        self._meter = metrics.get_meter("nohiki.kafka")

        self.messages_produced = self._meter.create_counter(
            "nohiki_kafka_messages_produced_total",
            description="Total messages produced to Kafka",
            unit="1",
        )
        self.messages_consumed = self._meter.create_counter(
            "nohiki_kafka_messages_consumed_total",
            description="Total messages consumed from Kafka",
            unit="1",
        )
        self.publish_duration = self._meter.create_histogram(
            "nohiki_kafka_publish_duration_seconds",
            description="Time to publish message to Kafka",
            unit="s",
        )
        self.processing_duration = self._meter.create_histogram(
            "nohiki_kafka_processing_duration_seconds",
            description="Time to process consumed message",
            unit="s",
        )
        self.consumer_lag = self._meter.create_up_down_counter(
            "nohiki_kafka_consumer_lag",
            description="Consumer lag in number of messages",
            unit="1",
        )
        self.dlq_messages = self._meter.create_counter(
            "nohiki_kafka_dlq_messages_total",
            description="Messages sent to dead letter queue",
            unit="1",
        )
        self.errors = self._meter.create_counter(
            "nohiki_kafka_errors_total",
            description="Kafka operation errors",
            unit="1",
        )
        self.retries = self._meter.create_counter(
            "nohiki_kafka_retries_total",
            description="Message processing retries",
            unit="1",
        )

    def record_message_produced(
        self,
        topic: str,
        duration_seconds: float,
        *,
        success: bool = True,
        partition: int | None = None,
    ) -> None:
        """Record a message production attempt."""
        attrs: dict[str, str | int] = {
            "topic": topic,
            "status": "success" if success else "error",
        }
        if partition is not None:
            attrs["partition"] = partition

        self.messages_produced.add(1, attrs)
        self.publish_duration.record(duration_seconds, attrs)

        if not success:
            self.errors.add(1, {"topic": topic, "operation": "produce"})

    def record_message_consumed(
        self,
        topic: str,
        consumer_group: str,
        duration_seconds: float,
        *,
        success: bool = True,
        handler: str | None = None,
    ) -> None:
        """Record a message consumption and processing."""
        attrs: dict[str, str] = {
            "topic": topic,
            "consumer_group": consumer_group,
            "status": "success" if success else "error",
        }
        if handler:
            attrs["handler"] = handler

        self.messages_consumed.add(1, attrs)
        self.processing_duration.record(duration_seconds, attrs)

        if not success:
            self.errors.add(1, {"topic": topic, "operation": "consume"})

    def record_dlq_message(
        self,
        topic: str,
        consumer_group: str,
        reason: str,
    ) -> None:
        """Record a message sent to DLQ."""
        self.dlq_messages.add(
            1,
            {
                "topic": topic,
                "consumer_group": consumer_group,
                "reason": reason,
            },
        )

    def record_retry(
        self,
        topic: str,
        consumer_group: str,
        attempt: int,
    ) -> None:
        """Record a retry attempt."""
        self.retries.add(
            1,
            {
                "topic": topic,
                "consumer_group": consumer_group,
                "attempt": str(attempt),
            },
        )

    def update_consumer_lag(
        self,
        topic: str,
        consumer_group: str,
        partition: int,
        lag: int,
    ) -> None:
        """Update consumer lag gauge."""
        self.consumer_lag.add(
            lag,
            {
                "topic": topic,
                "consumer_group": consumer_group,
                "partition": str(partition),
            },
        )


@lru_cache(maxsize=1)
def get_kafka_metrics() -> KafkaMetrics:
    """Get singleton KafkaMetrics instance."""
    return KafkaMetrics()

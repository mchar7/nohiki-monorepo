"""Data models for the Dead Letter Queue system."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nohiki_kafka_client.handlers import DLQStrategy


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """Information about a processing error."""

    error_type: str
    error_message: str
    error_stacktrace: str
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class ConsumedMessage:
    """Represents a consumed Kafka message."""

    topic: str
    partition: int
    offset: int
    timestamp: int
    headers: dict[str, str]
    key: str | None
    raw_value: bytes


@dataclass(slots=True)
class ProcessingContext:
    """Context for message processing."""

    consumer_group: str
    handler_name: str
    processing_start_time: float
    correlation_id: str | None = None
    additional_metadata: dict[str, object] | None = None

    def __post_init__(self) -> None:
        """Initialize additional metadata if not provided."""
        if self.additional_metadata is None:
            self.additional_metadata = {}


@dataclass(slots=True)
class DLQMessage:
    """Standardised DLQ message format for republishing."""

    source_topic: str
    original_partition: int
    original_offset: int
    original_timestamp: datetime
    original_headers: dict[str, str]
    original_payload: bytes
    original_key: str | None
    error_message: str
    error_type: str
    error_stacktrace: str
    retry_count: int
    first_failure_timestamp: datetime
    last_failure_timestamp: datetime
    processing_context: dict[str, object]
    consumer_group: str
    handler_name: str

    def to_dict(self) -> dict[str, object]:
        """Convert DLQ message to dictionary for serialization."""
        return {
            "source_topic": self.source_topic,
            "original_partition": self.original_partition,
            "original_offset": self.original_offset,
            "original_timestamp": self.original_timestamp.isoformat(),
            "original_headers": self.original_headers,
            "original_payload": self.original_payload.hex(),
            "original_key": self.original_key,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "error_stacktrace": self.error_stacktrace,
            "retry_count": self.retry_count,
            "first_failure_timestamp": self.first_failure_timestamp.isoformat(),
            "last_failure_timestamp": self.last_failure_timestamp.isoformat(),
            "processing_context": self.processing_context,
            "consumer_group": self.consumer_group,
            "handler_name": self.handler_name,
        }


@dataclass(slots=True)
class DLQResult:
    """Result of DLQ processing."""

    success: bool
    strategy_used: DLQStrategy
    dlq_topic: str | None = None
    error: Exception | None = None
    processing_time_ms: float = 0.0

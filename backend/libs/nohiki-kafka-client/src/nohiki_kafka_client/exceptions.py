"""Custom exceptions for nohiki-kafka-client."""


class KafkaClientError(Exception):
    """Base exception for all Kafka client errors."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize the exception with message and optional details.

        Args:
            message: Human-readable error description.
            details: Optional structured error context (error codes, IDs, etc.).

        """
        super().__init__(message)
        self.details: dict[str, object] = details or {}


class ConfigurationError(KafkaClientError):
    """Raised when there's an issue with client configuration."""


class KafkaConnectionError(KafkaClientError):
    """Raised when unable to connect to Kafka."""


class SerializationError(KafkaClientError):
    """Raised when message serialization/deserialization fails."""


class ProducerError(KafkaClientError):
    """Raised when producer operations fail."""


class ConsumerError(KafkaClientError):
    """Raised when consumer operations fail."""


class DLQError(KafkaClientError):
    """Raised when DLQ operations fail."""


class DLQPublishError(DLQError):
    """Raised when publishing to DLQ or retry topic fails.

    This is a critical error: the failed message cannot be safely committed
    because it would be permanently lost.  Callers must NOT mark the offset
    as completed when this error is raised.
    """


class CircuitBreakerOpenError(KafkaClientError):
    """Raised when circuit breaker is open and blocking operations."""


class ValidationError(KafkaClientError):
    """Raised when proto message fails protovalidate constraints."""

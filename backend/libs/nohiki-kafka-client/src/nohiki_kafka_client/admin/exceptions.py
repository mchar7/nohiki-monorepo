"""Admin-specific exceptions for nohiki-kafka-client."""

from nohiki_kafka_client.exceptions import KafkaClientError


class AdminError(KafkaClientError):
    """Raised when admin operations fail."""


class TopicAlreadyExistsError(AdminError):
    """Raised when creating a topic that already exists."""

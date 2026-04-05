"""Kafka client factory and auto-configuration."""

from .auto_client import AutoKafkaClient
from .factory import HasKafkaSettings, create_kafka_client, get_kafka_client

__all__ = [
    "AutoKafkaClient",
    "HasKafkaSettings",
    "create_kafka_client",
    "get_kafka_client",
]

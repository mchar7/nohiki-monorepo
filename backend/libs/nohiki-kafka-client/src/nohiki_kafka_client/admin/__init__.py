"""Kafka admin client module for topic management.

Provides :class:`KafkaAdmin` for creating, deleting, listing, and describing
Kafka topics through a high-level async API that hides aiokafka internals
behind library-defined types.

Usage::

    from nohiki_kafka_client.admin import KafkaAdmin, TopicSpec

    async with KafkaAdmin(config) as admin:
        result = await admin.ensure_topics_exist([
            TopicSpec(name="my-topic", num_partitions=6),
        ])
"""

from .client import KafkaAdmin
from .exceptions import AdminError, TopicAlreadyExistsError
from .models import EnsureTopicsResult, TopicDescription, TopicSpec

__all__ = [
    "AdminError",
    "EnsureTopicsResult",
    "KafkaAdmin",
    "TopicAlreadyExistsError",
    "TopicDescription",
    "TopicSpec",
]

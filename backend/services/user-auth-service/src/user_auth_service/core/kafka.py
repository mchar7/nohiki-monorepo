"""Kafka client for user-auth-service.

Producer-only Kafka client: user-auth-service publishes CDC events via the
transactional outbox and does not consume any Kafka topics.
Use `kafka_client.publish()` to send events; no consumers are registered.
"""

from nohiki_kafka_client import create_kafka_client

from user_auth_service.core.config import get_settings

kafka_client = create_kafka_client(get_settings())

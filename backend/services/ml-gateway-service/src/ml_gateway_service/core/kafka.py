"""Kafka client for ml-gateway-service.

Provides `kafka_client` module-level instance for:
- Decorator-based handler registration (@kafka_client.message_handler)
- Consumer lifecycle (start_consumers, stop_consumers)
- Event publishing (publish)

Handler modules must be imported before calling kafka_client.start_consumers().
See main.py lifespan for the handler registration pattern.
"""

from nohiki_kafka_client import create_kafka_client

from ml_gateway_service.core.config import get_settings

kafka_client = create_kafka_client(get_settings())

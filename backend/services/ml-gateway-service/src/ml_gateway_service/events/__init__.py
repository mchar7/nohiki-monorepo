"""Event handlers for ML gateway service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from nohiki_observability import get_logger

from ml_gateway_service.core.config import get_settings
from ml_gateway_service.core.kafka import kafka_client
from ml_gateway_service.events import batch_embedding, embedding, rerank

__all__ = ["batch_embedding", "embedding", "rerank", "start_event_consumer"]

logger = get_logger(__name__)
settings = get_settings()

_ = (batch_embedding, embedding, rerank)  # Ensure handlers are registered


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

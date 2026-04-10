"""Event handlers for doc-content-service.

Importing this module registers all Kafka handlers via decorator side effects.

Handler modules:
- handlers.py: Content generation request handler (primary command)
- upstream_cdc.py: Job correlation events for auto-generation eligibility
"""

from nohiki_observability import get_logger

from doc_content_service.core.config import get_settings
from doc_content_service.core.kafka import kafka_client
from doc_content_service.events import handlers, upstream_cdc

_ = (handlers, upstream_cdc)  # Ensure handlers are registered

logger = get_logger(__name__)
settings = get_settings()


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()


__all__ = ["handlers", "start_event_consumer", "upstream_cdc"]

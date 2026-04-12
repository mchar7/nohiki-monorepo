"""Event handlers for doc-template-service.

Importing this module registers all Kafka handlers via decorator side effects.

Handler modules:
- commands.py: Template CRUD command handlers (create, version add, delete)
- render_handler.py: Document render request handler
- publishers.py: Event publishing functions (used by handlers)
"""

from nohiki_observability import get_logger

from doc_template_service.core.config import get_settings
from doc_template_service.core.kafka import kafka_client
from doc_template_service.events import commands, render_handler
from doc_template_service.events.publishers import (
    build_template_snapshot,
    publish_template_created_event,
    publish_template_deleted_event,
    publish_template_updated_event,
)

_ = (commands, render_handler)  # Ensure handlers are registered

logger = get_logger(__name__)
settings = get_settings()


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()


__all__ = [
    "build_template_snapshot",
    "commands",
    "publish_template_created_event",
    "publish_template_deleted_event",
    "publish_template_updated_event",
    "render_handler",
    "start_event_consumer",
]

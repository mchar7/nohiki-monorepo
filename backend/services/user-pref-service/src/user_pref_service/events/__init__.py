"""Event handlers for user-pref-service.

Importing this module registers all Kafka handlers via decorator side effects.

Handler modules:
- commands.py: CRUD command handlers (create, update, delete profiles)
- callbacks.py: Async callback handlers (skill normalization, query encoding)
- upstream_cdc.py: CDC events from upstream services (user-auth, user-upload)
"""

from nohiki_observability import get_logger

from user_pref_service.core.config import get_settings
from user_pref_service.core.kafka import kafka_client
from user_pref_service.events import callbacks, commands, upstream_cdc

__all__ = ["callbacks", "commands", "start_event_consumer", "upstream_cdc"]

logger = get_logger(__name__)
settings = get_settings()


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

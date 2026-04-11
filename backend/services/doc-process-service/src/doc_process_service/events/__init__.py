"""Event handlers for doc-process-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from doc_process_service.events import handlers
from doc_process_service.events.handlers import start_event_consumer

__all__ = ["handlers", "start_event_consumer"]

_ = handlers  # Ensure handlers are registered via side effects

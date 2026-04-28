"""Event handlers for user-entitlement-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from user_entitlement_service.events import handlers
from user_entitlement_service.events.handlers import start_event_consumer

__all__ = ["handlers", "start_event_consumer"]

_ = handlers  # Ensure handlers are registered via side effects

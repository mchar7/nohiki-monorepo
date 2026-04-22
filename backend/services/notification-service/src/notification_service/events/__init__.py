"""Event handlers for notification-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from notification_service.events.handlers import start_event_consumer

__all__ = ["start_event_consumer"]

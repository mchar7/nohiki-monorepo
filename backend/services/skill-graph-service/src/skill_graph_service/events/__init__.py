"""Event handlers for skill-graph-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from skill_graph_service.events import handlers
from skill_graph_service.events.handlers import start_event_consumer

__all__ = ["start_event_consumer"]

_ = handlers  # Ensure handlers are registered via decorator side effects

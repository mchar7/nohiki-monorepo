"""Event handlers for job-query-composition-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from job_query_composition_service.events import handlers
from job_query_composition_service.events.handlers import start_event_consumer

__all__ = ["handlers", "start_event_consumer"]

_ = handlers  # Ensure handlers are registered via side effects
